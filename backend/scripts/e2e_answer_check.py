"""End-to-end check of the two refusal gates against a running deployment.

Unlike the built-in retrieval eval, this calls the real chat endpoint, so it
includes the language model: an out-of-scope question counts as refused if
either the retrieval gate or the model's NO_ANSWER sentinel declined it.

    python scripts/e2e_answer_check.py https://support-gpt.vercel.app

Creates one throwaway customer account and paces requests to stay under the
per-user chat rate limit (12/min). Takes about 7 minutes for the full set.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path

import httpx

GOLDEN = Path(__file__).resolve().parent.parent / "app" / "seed" / "golden.jsonl"


def main(base: str) -> None:
    items = [json.loads(x) for x in GOLDEN.read_text().splitlines() if x.strip() and not x.startswith("//")]
    c = httpx.Client(base_url=base.rstrip("/"), timeout=90, headers={"origin": base.rstrip("/")})
    r = c.post(
        "/api/auth/signup",
        json={
            "name": "E2E Check",
            "email": f"e2e.{secrets.token_hex(4)}@example.com",
            "password": "e2e-check-" + secrets.token_hex(6) + "9",
        },
    )
    r.raise_for_status()
    c.headers["x-csrf-token"] = r.json()["csrf_token"]

    rows = []
    for i, x in enumerate(items, 1):
        conv = c.post("/api/conversations").json()
        t0 = time.perf_counter()
        resp = c.post(f"/api/conversations/{conv['id']}/messages", json={"content": x["q"]})
        done = next(
            json.loads(b.split("\ndata: ", 1)[1])
            for b in resp.text.strip().split("\n\n")
            if b.startswith("event: done")
        )
        gate = "retrieval" if done["model"] is None and done["abstained"] else ("model" if done["abstained"] else None)
        rows.append(
            {
                "q": x["q"],
                "in_scope": bool(x.get("doc")),
                "abstained": done["abstained"],
                "gate": gate,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        )
        print(
            f"{i:>2}/{len(items)} {'IN ' if x.get('doc') else 'OUT'} refused={done['abstained']!s:<5} gate={gate}  {x['q'][:60]}"
        )
        time.sleep(5.5)

    ins = [r for r in rows if r["in_scope"]]
    outs = [r for r in rows if not r["in_scope"]]
    lat = sorted(r["latency_ms"] for r in ins if not r["abstained"])
    print(
        json.dumps(
            {
                "answerable": len(ins),
                "out_of_scope": len(outs),
                "false_refusal_rate": round(sum(r["abstained"] for r in ins) / len(ins), 4),
                "out_of_scope_refused": round(sum(r["abstained"] for r in outs) / len(outs), 4),
                "refused_by_retrieval_gate": sum(r["gate"] == "retrieval" for r in outs),
                "refused_by_model_gate": sum(r["gate"] == "model" for r in outs),
                "answer_latency_ms_p50": lat[len(lat) // 2] if lat else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
