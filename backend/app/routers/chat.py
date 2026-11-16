from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import audit, client_ip, get_current_user
from ..models import SLA_HOURS, Conversation, Message, Ticket, TicketMessage, User, utcnow
from ..ratelimit import enforce
from ..schemas import ConversationDetail, ConversationOut, EscalateIn, FeedbackIn, MessageIn, MessageOut
from ..services import rag
from ..services.assistant import (
    ABSTAIN_TEXT,
    LLM_DOWN_TEXT,
    NO_ANSWER,
    answer_messages,
    normalize_citations,
    retrieval_query,
    strip_unknown_citations,
    triage,
)
from ..services.guardrails import looks_like_injection, mask_cards
from ..services.llm import CallMeta, LLMUnavailable, gateway

log = logging.getLogger("supportgpt.chat")
router = APIRouter(prefix="/api", tags=["chat"])


def _own_conversation(db: Session, user: User, conv_id: int) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


def _ticket_for(db: Session, conv_id: int) -> Ticket | None:
    return db.scalar(select(Ticket).where(Ticket.conversation_id == conv_id))


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(50)
    ).all()


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce(f"conv-create:{user.id}", 30, 3600)
    conv = Conversation(user_id=user.id)
    db.add(conv)
    db.commit()
    return conv


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
def get_conversation(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conv_id)
    ticket = _ticket_for(db, conv.id)
    return ConversationDetail(
        **ConversationOut.model_validate(conv).model_dump(),
        messages=[MessageOut.model_validate(m) for m in conv.messages],
        ticket_id=ticket.id if ticket else None,
    )


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conv_id)
    db.delete(conv)
    db.commit()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/conversations/{conv_id}/messages")
def send_message(conv_id: int, body: MessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce(f"chat-min:{user.id}", 12, 60)
    enforce(f"chat-day:{user.id}", 200, 86400)
    conv = _own_conversation(db, user, conv_id)
    if conv.status == "escalated":
        raise HTTPException(
            status_code=409, detail="This conversation is with a support specialist now. Reply on the ticket."
        )

    text, masked = mask_cards(body.content)
    flagged = looks_like_injection(text)
    history = [(m.role, m.content) for m in conv.messages if m.role in ("user", "assistant") and not m.abstained]
    user_msg = Message(conversation_id=conv.id, role="user", content=text, flagged_injection=flagged)
    db.add(user_msg)
    if conv.title == "New conversation":
        conv.title = (text[:60] + ("..." if len(text) > 60 else "")).replace("\n", " ")
    conv.updated_at = utcnow()
    db.commit()
    user_msg_id, conversation_id = user_msg.id, conv.id
    settings = get_settings()

    def stream() -> Iterator[str]:
        started = time.perf_counter()
        yield _sse("meta", {"user_message_id": user_msg_id, "masked_cards": masked})
        sdb = SessionLocal()
        try:
            hits = rag.search(sdb, retrieval_query(text, history), k=5)
            conf = rag.confidence(hits)
            sources = [h.as_source(i) for i, h in enumerate(hits, start=1)]
            meta = CallMeta()
            abstained = conf < settings.abstain_threshold or not hits
            answer = ""

            if abstained:
                answer = ABSTAIN_TEXT
                yield _sse("sources", {"sources": [], "confidence": round(conf, 4)})
                yield _sse("token", {"t": answer})
            else:
                yield _sse("sources", {"sources": sources, "confidence": round(conf, 4)})
                pending = ""  # held back until we know it isn't the NO_ANSWER sentinel
                decided = False
                try:
                    for piece in gateway.stream(answer_messages(text, history, hits), settings.answer_models, meta):
                        answer += piece
                        if decided:
                            yield _sse("token", {"t": piece})
                            continue
                        pending += piece
                        head = pending.lstrip()
                        if head.startswith(NO_ANSWER):
                            abstained = True
                            break
                        if len(head) >= len(NO_ANSWER) or not NO_ANSWER.startswith(head):
                            decided = True
                            yield _sse("token", {"t": pending})
                    if not decided and not abstained:
                        head = pending.strip()
                        if len(head) >= 4 and NO_ANSWER.startswith(head):
                            abstained = True
                        elif pending:
                            yield _sse("token", {"t": pending})
                except LLMUnavailable:
                    answer = LLM_DOWN_TEXT
                    abstained = True
                    yield _sse("token", {"t": answer})
                if abstained and answer != LLM_DOWN_TEXT:
                    answer = ABSTAIN_TEXT
                    yield _sse("replace", {"text": answer, "sources": []})
                    sources = []
                else:
                    cleaned = strip_unknown_citations(normalize_citations(answer), len(sources))
                    if cleaned != answer:
                        answer = cleaned
                        yield _sse("replace", {"text": answer, "sources": sources})

            latency = int((time.perf_counter() - started) * 1000)
            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer.strip(),
                sources=sources if not abstained else [],
                confidence=round(conf, 4),
                abstained=abstained,
                latency_ms=latency,
                model=meta.model,
                key_used=meta.key,
            )
            sdb.add(msg)
            sdb.commit()
            yield _sse(
                "done",
                {
                    "message_id": msg.id,
                    "confidence": round(conf, 4),
                    "abstained": abstained,
                    "latency_ms": latency,
                    "model": meta.model,
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("chat stream failed")
            sdb.rollback()
            yield _sse("error", {"detail": "Something went wrong while answering. Please try again."})
        finally:
            sdb.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def message_feedback(
    message_id: int, body: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    msg = db.get(Message, message_id)
    if msg is None or msg.role != "assistant" or msg.conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Message not found.")
    msg.feedback = body.value
    db.commit()
    return msg


def _transcript(conv: Conversation) -> str:
    lines = []
    for m in conv.messages:
        who = "Customer" if m.role == "user" else "Assistant"
        lines.append(f"{who}: {m.content}")
    return "\n".join(lines)


@router.post("/conversations/{conv_id}/escalate")
def escalate(
    conv_id: int,
    body: EscalateIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce(f"escalate:{user.id}", 10, 3600)
    conv = _own_conversation(db, user, conv_id)
    existing = _ticket_for(db, conv.id)
    if existing:
        return {"ticket_id": existing.id, "created": False}
    user_msgs = [m for m in conv.messages if m.role == "user"]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="Ask a question first so we know what to pass along.")

    note = mask_cards(body.note)[0] if body.note else None
    transcript = _transcript(conv) + (f"\nCustomer note for the agent: {note}" if note else "")
    t, source = triage(transcript, user_msgs[0].content)
    now = datetime.now(UTC)
    ticket = Ticket(
        customer_id=user.id,
        conversation_id=conv.id,
        subject=t.subject,
        summary=t.summary,
        category=t.category,
        priority=t.priority,
        sentiment=t.sentiment,
        triage_source=source,
        status="open",
        sla_due_at=now + timedelta(hours=SLA_HOURS[t.priority]),
    )
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id, kind="customer", body=note or user_msgs[-1].content))
    conv.status = "escalated"
    conv.updated_at = now
    audit(
        db,
        user,
        "ticket.escalated",
        target=f"ticket:{ticket.id}",
        meta={"category": t.category, "priority": t.priority, "triage": source},
        ip=client_ip(request),
    )
    db.commit()
    return {"ticket_id": ticket.id, "created": True}
