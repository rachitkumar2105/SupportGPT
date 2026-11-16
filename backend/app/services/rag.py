"""Retrieval: structure-aware chunking, local embeddings, and hybrid search.

Hybrid search fuses two rankers with Reciprocal Rank Fusion (RRF, k=60):

* Dense: cosine similarity over BAAI/bge-small-en-v1.5 embeddings (384-d,
  ONNX via fastembed, no torch). Good at paraphrases ("get my money back").
* Sparse: Okapi BM25, implemented here (~60 lines). Good at exact tokens that
  embeddings blur: plan names, error codes, numbers ("E-402", "Team plan").

The in-process index is rebuilt only when ``kb_state.version`` changes, so a
request costs one tiny SELECT plus a matrix-vector product. The DB stays the
source of truth; nothing is cached that another worker could disagree with.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Chunk, Document, KBState

DIM = 384
TARGET_CHARS = 900
MAX_CHARS = 1300
RRF_K = 60
CANDIDATES = 20

# ---------------------------------------------------------------- embeddings


class _HashEmbedder:
    """Deterministic bag-of-words embedder used only in tests (no model download)."""

    def embed(self, texts: list[str]):
        for t in texts:
            v = np.zeros(DIM, dtype="float32")
            for tok in tokenize(t):
                h = int(hashlib.md5(tok.encode(), usedforsecurity=False).hexdigest(), 16)
                v[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
            yield v


_embedder = None
_embedder_lock = threading.Lock()


def get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                if get_settings().embedder == "hash":
                    _embedder = _HashEmbedder()
                else:
                    from fastembed import TextEmbedding

                    _embedder = TextEmbedding(
                        model_name="BAAI/bge-small-en-v1.5", cache_dir=os.environ.get("FASTEMBED_CACHE_PATH")
                    )
    return _embedder


def embedder_ready() -> bool:
    return _embedder is not None


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    m = np.asarray(list(get_embedder().embed(texts)), dtype="float32")
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


# bge models are trained with this instruction prefix for short queries.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def embed_query(text: str) -> np.ndarray:
    prefix = "" if get_settings().embedder == "hash" else QUERY_PREFIX
    return embed([prefix + text])[0]


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype="float32").tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="float32")


# ------------------------------------------------------------------ chunking

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")


@dataclass
class ChunkDraft:
    content: str
    heading: str | None
    page: int | None


def _pack(paragraphs: list[str], heading: str | None, page: int | None) -> list[ChunkDraft]:
    """Greedy-packs paragraphs up to TARGET_CHARS, never splitting mid-paragraph unless
    a single paragraph exceeds MAX_CHARS (then it is split on sentence boundaries)."""
    units: list[str] = []
    for p in paragraphs:
        if len(p) <= MAX_CHARS:
            units.append(p)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p)
        buf = ""
        for s in sentences:
            if buf and len(buf) + len(s) + 1 > TARGET_CHARS:
                units.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            units.append(buf)

    chunks: list[ChunkDraft] = []
    buf: list[str] = []
    size = 0
    for u in units:
        if buf and size + len(u) > TARGET_CHARS:
            chunks.append(ChunkDraft("\n\n".join(buf), heading, page))
            # one-paragraph overlap keeps answers that straddle a boundary retrievable
            tail = buf[-1] if len(buf[-1]) < 300 else ""
            buf, size = ([tail] if tail else []), len(tail)
        buf.append(u)
        size += len(u)
    if buf:
        chunks.append(ChunkDraft("\n\n".join(buf), heading, page))
    return chunks


def chunk_markdown(text: str, page: int | None = None) -> list[ChunkDraft]:
    """Splits on markdown headings first so a chunk never mixes two sections."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    para: list[str] = []

    def flush_para():
        if para:
            joined = " ".join(line.strip() for line in para).strip()
            if joined:
                sections[-1][1].append(joined)
            para.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush_para()
            sections.append((m.group(2).strip(), []))
        elif not line.strip():
            flush_para()
        elif line.lstrip().startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ")):
            flush_para()
            para.append(line)
            flush_para()
        else:
            para.append(line)
    flush_para()

    out: list[ChunkDraft] = []
    for heading, paragraphs in sections:
        if paragraphs:
            out.extend(_pack(paragraphs, heading, page))
    return out


def chunk_pages(pages: list[str]) -> list[ChunkDraft]:
    out: list[ChunkDraft] = []
    for i, text in enumerate(pages, start=1):
        out.extend(chunk_markdown(text, page=i))
    return out


def embedding_text(doc_title: str, d: ChunkDraft) -> str:
    # Section context makes short chunks ("It takes 5 business days.") retrievable.
    head = f"{doc_title} > {d.heading}" if d.heading else doc_title
    return f"{head}\n{d.content}"


# --------------------------------------------------------------------- BM25

_STOP = set(
    "a an and are as at be but by can do does for from has have how i if in into is it its me my "
    "no not of on or our so that the their then there these this to was we what when where which "
    "who why will with you your".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def _stem(t: str) -> str:
    for suf in ("ings", "ing", "edly", "ed", "ies", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lens = np.array([len(d) for d in docs], dtype="float32")
        self.avgdl = float(self.lens.mean()) if self.n else 0.0
        self.tfs = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        # BM25+ style floor keeps idf positive for very common terms.
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n, dtype="float32")
        if not self.n:
            return out
        norm = self.k1 * (1 - self.b + self.b * self.lens / (self.avgdl or 1.0))
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([c.get(term, 0) for c in self.tfs], dtype="float32")
            out += idf * tf * (self.k1 + 1) / (tf + norm)
        return out


# ------------------------------------------------------------- hybrid index


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    doc_title: str
    doc_slug: str
    heading: str | None
    page: int | None
    content: str
    dense: float
    bm25: float
    dense_rank: int | None
    bm25_rank: int | None
    rrf: float

    def as_source(self, n: int) -> dict:
        d = asdict(self)
        d["n"] = n
        d["snippet"] = self.content[:320]
        d.pop("content")
        d["dense"] = round(self.dense, 4)
        d["bm25"] = round(self.bm25, 3)
        d["rrf"] = round(self.rrf, 5)
        return d


class _Index:
    def __init__(self, version: int, rows: list[tuple]) -> None:
        self.version = version
        self.rows = rows  # (chunk_id, doc_id, title, slug, heading, page, content)
        self.matrix = np.vstack([from_blob(r[7]) for r in rows]) if rows else np.zeros((0, DIM), dtype="float32")
        self.rows = [r[:7] for r in rows]
        self.bm25 = BM25([tokenize(f"{r[2]} {r[4] or ''} {r[6]}") for r in rows])


_index: _Index | None = None
_index_lock = threading.Lock()


def kb_version(db: Session) -> int:
    v = db.scalar(select(KBState.version).where(KBState.id == 1))
    return int(v or 0)


def bump_kb_version(db: Session) -> None:
    state = db.get(KBState, 1)
    if state is None:
        db.add(KBState(id=1, version=1))
    else:
        state.version += 1


def _get_index(db: Session) -> _Index:
    global _index
    version = kb_version(db)
    if _index is not None and _index.version == version:
        return _index
    with _index_lock:
        if _index is None or _index.version != version:
            rows = db.execute(
                select(
                    Chunk.id,
                    Document.id,
                    Document.title,
                    Document.slug,
                    Chunk.heading,
                    Chunk.page,
                    Chunk.content,
                    Chunk.embedding,
                )
                .join(Document, Document.id == Chunk.document_id)
                .order_by(Chunk.id)
            ).all()
            _index = _Index(version, [tuple(r) for r in rows])
    return _index


def reset_index_cache() -> None:
    global _index
    _index = None


def _ranks(scores: np.ndarray, n: int) -> list[int]:
    if scores.size == 0:
        return []
    n = min(n, scores.size)
    idx = np.argpartition(-scores, n - 1)[:n]
    return idx[np.argsort(-scores[idx])].tolist()


def search(db: Session, query: str, k: int = 5, mode: str = "hybrid", query_vec: np.ndarray | None = None) -> list[Hit]:
    """mode: 'hybrid' | 'dense' | 'bm25'. Every Hit carries both raw scores and ranks."""
    idx = _get_index(db)
    if not idx.rows:
        return []
    qv = query_vec if query_vec is not None else embed_query(query)
    dense = idx.matrix @ qv
    sparse = idx.bm25.scores(tokenize(query))

    d_order = _ranks(dense, CANDIDATES)
    s_order = [i for i in _ranks(sparse, CANDIDATES) if sparse[i] > 0]
    d_rank = {i: r for r, i in enumerate(d_order, start=1)}
    s_rank = {i: r for r, i in enumerate(s_order, start=1)}

    if mode == "dense":
        order = d_order
        fused = {i: 1.0 / (RRF_K + d_rank[i]) for i in order}
    elif mode == "bm25":
        order = s_order
        fused = {i: 1.0 / (RRF_K + s_rank[i]) for i in order}
    else:
        fused = {}
        for i in set(d_order) | set(s_order):
            fused[i] = (1.0 / (RRF_K + d_rank[i]) if i in d_rank else 0.0) + (
                1.0 / (RRF_K + s_rank[i]) if i in s_rank else 0.0
            )
        order = sorted(fused, key=lambda i: -fused[i])

    hits = []
    for i in order[:k]:
        cid, did, title, slug, heading, page, content = idx.rows[i]
        hits.append(
            Hit(
                cid,
                did,
                title,
                slug,
                heading,
                page,
                content,
                float(dense[i]),
                float(sparse[i]),
                d_rank.get(i),
                s_rank.get(i),
                float(fused[i]),
            )
        )
    return hits


def confidence(hits: list[Hit]) -> float:
    """Calibrated-by-eval confidence proxy: best dense cosine among the fused top hits."""
    return max((h.dense for h in hits), default=0.0)


def index_stats(db: Session) -> dict:
    idx = _get_index(db)
    return {"chunks": len(idx.rows), "kb_version": idx.version}
