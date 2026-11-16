from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..deps import audit, client_ip, require_admin, require_staff
from ..models import Document, User
from ..ratelimit import enforce
from ..schemas import DocumentDetail, DocumentOut, SearchIn
from ..services import rag
from ..services.ingest import clean_title, ingest

router = APIRouter(prefix="/api/kb", tags=["knowledge base"])


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.source.desc(), Document.title)).all()


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    doc = db.scalar(select(Document).where(Document.id == doc_id).options(selectinload(Document.chunks)))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc.chunks.sort(key=lambda c: c.ord)
    return doc


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data.extend(chunk)
        if len(data) > cap:
            raise HTTPException(status_code=413, detail=f"Files are limited to {cap // (1024 * 1024)} MB.")
    return bytes(data)


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce(f"upload:{user.id}", 20, 3600)
    data = await _read_capped(file, get_settings().max_upload_bytes)
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    doc_title = clean_title(title or file.filename)
    doc = ingest(db, title=doc_title, data=data, source="upload", uploader=user)
    audit(
        db,
        user,
        "kb.upload",
        target=f"document:{doc.id}",
        meta={"title": doc.title, "chunks": doc.chunk_count, "bytes": doc.size_bytes},
        ip=client_ip(request),
    )
    db.commit()
    return doc


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    audit(db, user, "kb.delete", target=f"document:{doc.id}", meta={"title": doc.title}, ip=client_ip(request))
    db.delete(doc)
    rag.bump_kb_version(db)
    db.commit()


@router.post("/search")
def inspect_search(body: SearchIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Retrieval inspector: the same query through dense, BM25 and hybrid, side by side."""
    enforce(f"inspect:{user.id}", 30, 60)
    t0 = time.perf_counter()
    qv = rag.embed_query(body.query)
    out = {}
    for mode in ("hybrid", "dense", "bm25"):
        hits = rag.search(db, body.query, k=body.k, mode=mode, query_vec=qv)
        out[mode] = [h.as_source(i) for i, h in enumerate(hits, start=1)]
    hybrid_conf = rag.confidence(rag.search(db, body.query, k=5, query_vec=qv))
    return {
        "results": out,
        "confidence": round(hybrid_conf, 4),
        "would_abstain": hybrid_conf < get_settings().abstain_threshold,
        "threshold": get_settings().abstain_threshold,
        "took_ms": int((time.perf_counter() - t0) * 1000),
    }
