"""Real retrieval-augmented generation: chunking, local embeddings, and
per-query FAISS similarity search.

Embeddings are computed with fastembed (ONNX runtime, no torch dependency —
sentence-transformers/torchvision pulls in a broken torch/torchvision ABI on
this environment, see README "Challenges Overcome"). Chunk vectors are
persisted in the DB (DocumentChunk.embedding) rather than cached in process
memory, so retrieval is correct across multiple uvicorn/gunicorn workers: each
request rebuilds a small FAISS index on the fly from the DB rows for that
user, instead of relying on worker-local state.
"""
import re
import threading
import numpy as np
import faiss

EMBEDDING_DIM = 384
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
RELEVANCE_THRESHOLD = 0.3  # cosine similarity below this = "not relevant enough"

_embedder = None
_embedder_lock = threading.Lock()
_PAGE_MARKER = re.compile(r"--- Page (\d+) ---")


def _get_embedder():
    # FastAPI's sync endpoints run in a threadpool, so concurrent first
    # requests could otherwise race here and construct/load the ONNX model
    # more than once. Double-checked locking avoids that without paying for
    # a lock on every call once the singleton is warm.
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                from fastembed import TextEmbedding
                _embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _embedder


def embed_texts(texts):
    """Returns an (N, EMBEDDING_DIM) float32 array of L2-normalized vectors."""
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype="float32")
    vectors = np.array(list(_get_embedder().embed(texts)), dtype="float32")
    faiss.normalize_L2(vectors)
    return vectors


def embed_query(text: str):
    return embed_texts([text])[0]


def _chunk_plain(text: str, page):
    text = text.strip()
    if not text:
        return []
    chunks = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + CHUNK_SIZE, n)
        piece = text[start:end].strip()
        if piece:
            chunks.append({"content": piece, "page": page})
        if end == n:
            break
        start = end - CHUNK_OVERLAP
    return chunks


def chunk_document(text: str):
    """Splits text into overlapping chunks, tracking page numbers from the
    '--- Page N ---' markers left by extract_text_from_pdf. Non-PDF text has
    no markers and is chunked with page=None."""
    if not text:
        return []
    parts = _PAGE_MARKER.split(text)
    if len(parts) == 1:
        return _chunk_plain(text, page=None)

    chunks = []
    pre = parts[0].strip()
    if pre:
        chunks.extend(_chunk_plain(pre, page=None))
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        page_text = parts[i + 1] if i + 1 < len(parts) else ""
        chunks.extend(_chunk_plain(page_text, page=page_num))
    return chunks


def top_k(query_vector, candidate_vectors, k=5):
    """candidate_vectors: (N, dim) float32, L2-normalized. Returns (indices, scores)
    sorted by descending cosine similarity."""
    if candidate_vectors.shape[0] == 0:
        return [], []
    index = faiss.IndexFlatIP(candidate_vectors.shape[1])
    index.add(candidate_vectors)
    k = min(k, candidate_vectors.shape[0])
    scores, indices = index.search(query_vector.reshape(1, -1).astype("float32"), k)
    return indices[0].tolist(), scores[0].tolist()


def vector_to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype="float32").tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="float32")
