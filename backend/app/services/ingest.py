"""Turning uploaded bytes into indexed chunks.

Files are never written to disk: the Space's filesystem is ephemeral and
untrusted filenames never touch a path. Type is decided by content (magic
bytes / UTF-8 decodability), not by the client-sent extension or MIME type.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Document, User
from . import rag

MAX_PDF_PAGES = 200
MAX_CHUNKS = 1500


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:100] or "document"


def clean_title(filename: str | None, fallback: str = "Untitled document") -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"\.(pdf|md|markdown|txt)$", "", name, flags=re.I)
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"[^\w .,()&'-]", "", name).strip()
    return (name[:120] or fallback).strip()


def sniff(data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Only PDF, Markdown and plain-text files are supported.") from None
    # Reject binary blobs that happen to decode (lots of control chars).
    ctrl = sum(1 for c in text[:4000] if ord(c) < 32 and c not in "\n\r\t")
    if ctrl > 20:
        raise HTTPException(status_code=415, detail="That file doesn't look like readable text.")
    return "text/markdown"


def extract_pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise HTTPException(status_code=422, detail="Encrypted PDFs aren't supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail=f"PDFs are limited to {MAX_PDF_PAGES} pages.")
        return [(p.extract_text() or "") for p in reader.pages]
    except PdfReadError:
        raise HTTPException(status_code=422, detail="This PDF couldn't be read. It may be damaged.") from None


def ingest(
    db: Session, *, title: str, data: bytes, source: str, uploader: User | None, mime: str | None = None
) -> Document:
    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == sha))
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"This file is already in the knowledge base as '{existing.title}'."
        )

    mime = mime or sniff(data)
    if mime == "application/pdf":
        drafts = rag.chunk_pages(extract_pdf_pages(data))
    else:
        drafts = rag.chunk_markdown(data.decode("utf-8"))
    drafts = [d for d in drafts if len(d.content.strip()) >= 40]
    if not drafts:
        raise HTTPException(
            status_code=422, detail="No readable text was found in this file. Scanned PDFs need OCR first."
        )
    if len(drafts) > MAX_CHUNKS:
        raise HTTPException(status_code=413, detail="This document is too large to index.")

    vectors = rag.embed([rag.embedding_text(title, d) for d in drafts])
    doc = Document(
        title=title,
        slug=slugify(title),
        source=source,
        mime=mime,
        size_bytes=len(data),
        sha256=sha,
        chunk_count=len(drafts),
        uploaded_by=uploader.id if uploader else None,
    )
    db.add(doc)
    db.flush()
    for i, (d, v) in enumerate(zip(drafts, vectors, strict=True)):
        db.add(
            Chunk(
                document_id=doc.id,
                ord=i,
                heading=(d.heading or None) and d.heading[:200],
                page=d.page,
                content=d.content,
                embedding=rag.to_blob(v),
            )
        )
    rag.bump_kb_version(db)
    return doc
