from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import audit, client_ip, get_current_user, require_staff
from ..models import SLA_HOURS, Conversation, Ticket, TicketMessage, User, aware
from ..ratelimit import enforce
from ..schemas import (
    CsatIn,
    DraftOut,
    MessageOut,
    TicketCreateIn,
    TicketDetail,
    TicketMessageOut,
    TicketOut,
    TicketPatchIn,
    TicketReplyIn,
)
from ..services import rag
from ..services.assistant import draft_reply, triage
from ..services.guardrails import mask_cards
from ..services.llm import LLMUnavailable

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

STAFF = ("agent", "admin")


def _load(db: Session, ticket_id: int) -> Ticket:
    t = db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.messages).selectinload(TicketMessage.author),
            selectinload(Ticket.customer),
            selectinload(Ticket.assignee),
        )
    )
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


def _visible(db: Session, user: User, ticket_id: int) -> Ticket:
    t = _load(db, ticket_id)
    if user.role not in STAFF and t.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


def _detail(db: Session, t: Ticket, user: User) -> TicketDetail:
    staff = user.role in STAFF
    msgs = [
        TicketMessageOut(
            id=m.id,
            kind=m.kind,
            body=m.body,
            ai_assisted=m.ai_assisted,
            created_at=m.created_at,
            author_name=(m.author.name if m.author else None),
        )
        for m in t.messages
        if staff or m.kind != "note"
    ]
    transcript = []
    if t.conversation_id:
        conv = db.get(Conversation, t.conversation_id)
        if conv:
            transcript = [MessageOut.model_validate(m) for m in conv.messages]
    base = TicketOut.model_validate(t).model_dump()
    return TicketDetail(**base, messages=msgs, transcript=transcript, csat_comment=t.csat_comment)


@router.get("", response_model=list[TicketOut])
def list_tickets(
    status: str | None = Query(default=None, pattern="^(open|pending|resolved|active|all)$"),
    priority: str | None = Query(default=None, pattern="^(low|medium|high|urgent)$"),
    category: str | None = Query(default=None, pattern="^(billing|account|technical|data|other)$"),
    mine: bool = False,
    q: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Ticket).options(selectinload(Ticket.customer), selectinload(Ticket.assignee))
    if user.role not in STAFF:
        stmt = stmt.where(Ticket.customer_id == user.id)
    if status in (None, "active"):
        stmt = stmt.where(Ticket.status.in_(("open", "pending")))
    elif status != "all":
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if mine:
        stmt = stmt.where(Ticket.assignee_id == user.id)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(Ticket.subject.ilike(like), Ticket.summary.ilike(like)))
    resolved_last = case((Ticket.status == "resolved", 1), else_=0)
    stmt = stmt.order_by(resolved_last, Ticket.sla_due_at.asc(), Ticket.id.desc()).limit(200)
    return db.scalars(stmt).all()


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(
    body: TicketCreateIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    enforce(f"ticket-create:{user.id}", 10, 3600)
    text = mask_cards(body.body)[0]
    t, source = triage(f"Subject: {body.subject}\nCustomer: {text}", body.subject)
    now = datetime.now(UTC)
    ticket = Ticket(
        customer_id=user.id,
        subject=body.subject,
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
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id, kind="customer", body=text))
    audit(db, user, "ticket.created", target=f"ticket:{ticket.id}", ip=client_ip(request))
    db.commit()
    db.expire_all()
    return _load(db, ticket.id)


@router.get("/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, _visible(db, user, ticket_id), user)


@router.post("/{ticket_id}/messages", response_model=TicketDetail, status_code=201)
def reply(
    ticket_id: int,
    body: TicketReplyIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce(f"ticket-reply:{user.id}", 30, 600)
    t = _visible(db, user, ticket_id)
    now = datetime.now(UTC)
    text = mask_cards(body.body)[0]
    if user.role in STAFF:
        kind = "note" if body.internal else "agent"
        db.add(TicketMessage(ticket_id=t.id, author_id=user.id, kind=kind, body=text, ai_assisted=body.ai_assisted))
        if kind == "agent":
            if t.first_response_at is None:
                t.first_response_at = now
            if t.status == "open":
                t.status = "pending"
            if t.assignee_id is None:
                t.assignee_id = user.id
    else:
        if body.internal:
            raise HTTPException(status_code=403, detail="Only agents can add internal notes.")
        db.add(TicketMessage(ticket_id=t.id, author_id=user.id, kind="customer", body=text))
        if t.status in ("pending", "resolved"):
            t.status = "open"
            t.resolved_at = None
    t.updated_at = now
    audit(db, user, "ticket.reply", target=f"ticket:{t.id}", meta={"internal": body.internal}, ip=client_ip(request))
    db.commit()
    db.expire_all()
    return _detail(db, _load(db, t.id), user)


@router.post("/{ticket_id}/draft", response_model=DraftOut)
def ai_draft(ticket_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    enforce(f"draft:{user.id}", 15, 600)
    t = _load(db, ticket_id)
    thread = []
    if t.conversation_id:
        conv = db.get(Conversation, t.conversation_id)
        if conv:
            thread += [f"{'Customer' if m.role == 'user' else 'Assistant'}: {m.content}" for m in conv.messages]
    thread += [f"{m.kind.title()}: {m.body}" for m in t.messages if m.kind != "note"]
    last_customer = next((m.body for m in reversed(t.messages) if m.kind == "customer"), t.subject)
    hits = rag.search(db, f"{t.subject} {last_customer}", k=4)
    try:
        d = draft_reply("\n".join(thread), t.customer.name.split(" ")[0], hits)
    except LLMUnavailable:
        raise HTTPException(
            status_code=503, detail="The drafting model is unavailable right now. Try again shortly."
        ) from None
    return DraftOut(text=d.text, sources=d.sources, model=d.model)


@router.patch("/{ticket_id}", response_model=TicketDetail)
def update_ticket(
    ticket_id: int,
    body: TicketPatchIn,
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    t = _load(db, ticket_id)
    changes = body.model_dump(exclude_unset=True)
    now = datetime.now(UTC)
    if "assignee_id" in changes:
        aid = changes["assignee_id"]
        if aid in (None, 0):
            t.assignee_id = None
        else:
            assignee = db.get(User, aid)
            if assignee is None or assignee.role not in STAFF or not assignee.is_active:
                raise HTTPException(status_code=422, detail="Tickets can only be assigned to active agents.")
            t.assignee_id = aid
    if body.priority and body.priority != t.priority:
        t.priority = body.priority
        t.sla_due_at = aware(t.created_at) + timedelta(hours=SLA_HOURS[body.priority])
    if body.category:
        t.category = body.category
    if body.status and body.status != t.status:
        t.status = body.status
        t.resolved_at = now if body.status == "resolved" else None
        db.add(
            TicketMessage(
                ticket_id=t.id, author_id=user.id, kind="system", body=f"{user.name} marked this ticket {body.status}."
            )
        )
    t.updated_at = now
    audit(
        db,
        user,
        "ticket.updated",
        target=f"ticket:{t.id}",
        meta={k: v for k, v in changes.items()},
        ip=client_ip(request),
    )
    db.commit()
    db.expire_all()
    return _detail(db, _load(db, t.id), user)


@router.post("/{ticket_id}/csat", response_model=TicketDetail)
def rate_ticket(ticket_id: int, body: CsatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _visible(db, user, ticket_id)
    if t.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Only the customer can rate this ticket.")
    if t.status != "resolved":
        raise HTTPException(status_code=409, detail="You can rate a ticket once it's resolved.")
    if t.csat is not None:
        raise HTTPException(status_code=409, detail="You've already rated this ticket. Thank you!")
    t.csat = body.score
    t.csat_comment = body.comment
    db.commit()
    db.expire_all()
    return _detail(db, _load(db, t.id), user)
