"""Retrieval + abstention evaluation over a hand-written golden set.

Questions are deliberately paraphrased (they avoid the article's wording) so
BM25 can't win on copy-paste overlap. Out-of-scope questions have doc=null and
measure whether the abstention threshold correctly refuses to answer.

No LLM is called: this measures the retrieval layer the answers are built on,
so it is cheap, deterministic for a given KB version, and safe to run often.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from ..config import get_settings
from . import rag

GOLDEN = Path(__file__).resolve().parent.parent / "seed" / "golden.jsonl"


def load_golden() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip() and not line.startswith("//")]


def run_eval(db: Session) -> dict:
    items = load_golden()
    answerable = [x for x in items if x.get("doc")]
    unanswerable = [x for x in items if not x.get("doc")]
    modes = ("hybrid", "dense", "bm25")
    ranks: dict[str, list[int | None]] = {m: [] for m in modes}
    confs_in: list[float] = []
    confs_out: list[float] = []
    latencies: list[float] = []
    misses: list[dict] = []

    for x in items:
        t0 = time.perf_counter()
        qv = rag.embed_query(x["q"])
        hybrid_top5 = rag.search(db, x["q"], k=5, mode="hybrid", query_vec=qv)
        latencies.append((time.perf_counter() - t0) * 1000)
        conf = rag.confidence(hybrid_top5)
        if not x.get("doc"):
            confs_out.append(conf)
            continue
        confs_in.append(conf)
        for m in modes:
            hits = hybrid_top5 if m == "hybrid" else rag.search(db, x["q"], k=5, mode=m, query_vec=qv)
            rank = next((i for i, h in enumerate(hits, start=1) if h.doc_slug == x["doc"]), None)
            ranks[m].append(rank)
            if m == "hybrid" and rank != 1:
                misses.append({"q": x["q"], "expected": x["doc"], "got": [h.doc_slug for h in hits[:3]], "rank": rank})

    def summarise(rs: list[int | None]) -> dict:
        n = len(rs) or 1
        return {
            "hit@1": round(sum(1 for r in rs if r == 1) / n, 4),
            "hit@3": round(sum(1 for r in rs if r and r <= 3) / n, 4),
            "hit@5": round(sum(1 for r in rs if r and r <= 5) / n, 4),
            "mrr": round(sum(1 / r for r in rs if r) / n, 4),
        }

    thr = get_settings().abstain_threshold

    def abstention_at(t: float) -> dict:
        tp = sum(1 for c in confs_out if c < t)  # correctly refused
        fn = len(confs_out) - tp  # answered something out of scope
        fp = sum(1 for c in confs_in if c < t)  # refused an answerable question
        tn = len(confs_in) - fp
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        bal = 0.5 * (rec + (tn / (tn + fp) if tn + fp else 0.0))
        return {
            "threshold": round(t, 2),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "false_refusal_rate": round(fp / len(confs_in), 4) if confs_in else 0.0,
            "balanced_accuracy": round(bal, 4),
        }

    sweep = [abstention_at(t) for t in np.arange(0.50, 0.91, 0.01)]
    best = max(sweep, key=lambda r: (r["balanced_accuracy"], -r["false_refusal_rate"]))

    return {
        "n_answerable": len(answerable),
        "n_out_of_scope": len(unanswerable),
        "retrieval": {m: summarise(ranks[m]) for m in modes},
        "abstention": {"current": abstention_at(thr), "best": best, "sweep": sweep},
        "confidence": {
            "answerable_median": round(statistics.median(confs_in), 4) if confs_in else None,
            "out_of_scope_median": round(statistics.median(confs_out), 4) if confs_out else None,
        },
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "p95": round(float(np.percentile(latencies, 95)), 1) if latencies else None,
        },
        "hybrid_misses": misses[:25],
    }
