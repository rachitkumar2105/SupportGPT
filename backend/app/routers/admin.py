from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, client_ip, require_admin, require_staff
from ..models import AuditLog, Conversation, EvalRun, Message, Ticket, User, aware
from ..ratelimit import enforce
from ..schemas import UserOut, UserPatchIn
from ..security import revoke_all_for_user
from ..services import rag
from ..services.evaluation import run_eval

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(require_admin), db: Session = Depends(get_db), q: str | None = Query(default=None, max_length=100)
):
    stmt = select(User).order_by(User.created_at.desc()).limit(300)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.name.ilike(like)))
    return db.scalars(stmt).all()


@router.get("/agents", response_model=list[UserOut])
def list_agents(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.role.in_(("agent", "admin")), User.is_active.is_(True))).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int,
    body: UserPatchIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't change your own role or status.")
    if target.is_demo:
        raise HTTPException(status_code=400, detail="The demo account is managed by configuration.")
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] != target.role:
        target.role = changes["role"]
        target.token_version += 1  # new role takes effect on next refresh, old tokens die now
    if "is_active" in changes and changes["is_active"] != target.is_active:
        target.is_active = changes["is_active"]
        target.token_version += 1
        if not target.is_active:
            revoke_all_for_user(db, target.id)
    audit(db, admin, "admin.user_updated", target=f"user:{target.id}", meta=changes, ip=client_ip(request))
    db.commit()
    return target


@router.get("/audit")
def audit_log(_: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = Query(100, le=300)):
    rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ).all()
    return [
        {"id": a.id, "action": a.action, "target": a.target, "meta": a.meta, "actor": email, "created_at": a.created_at}
        for a, email in rows
    ]


@router.get("/analytics")
def analytics(days: int = Query(14, ge=1, le=90), _: User = Depends(require_staff), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    # Sample/demo accounts are excluded so the numbers only reflect real usage.
    demo_ids = select(User.id).where(User.is_demo.is_(True))
    convs = db.scalars(
        select(Conversation).where(Conversation.created_at >= since, Conversation.user_id.not_in(demo_ids))
    ).all()
    conv_ids = {c.id for c in convs}
    answers = [
        m
        for m in db.scalars(select(Message).where(Message.created_at >= since, Message.role == "assistant")).all()
        if m.conversation_id in conv_ids
    ]
    user_msgs = (
        db.scalar(select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "user")) or 0
    )
    flagged = (
        db.scalar(
            select(func.count(Message.id)).where(Message.created_at >= since, Message.flagged_injection.is_(True))
        )
        or 0
    )
    tickets = db.scalars(select(Ticket).where(Ticket.created_at >= since, Ticket.customer_id.not_in(demo_ids))).all()
    open_tickets = db.scalars(
        select(Ticket).where(Ticket.status.in_(("open", "pending")), Ticket.customer_id.not_in(demo_ids))
    ).all()

    answered_convs = {m.conversation_id for m in answers if not m.abstained}
    escalated_convs = {t.conversation_id for t in tickets if t.conversation_id}
    convs_with_answers = [c for c in convs if c.id in answered_convs or c.id in escalated_convs]
    deflected = [c for c in convs_with_answers if c.id not in escalated_convs]

    latencies = [m.latency_ms for m in answers if m.latency_ms is not None and not m.abstained]
    confs = [m.confidence for m in answers if m.confidence is not None]
    up = sum(1 for m in answers if m.feedback == 1)
    down = sum(1 for m in answers if m.feedback == -1)
    keys = Counter(m.key_used for m in answers if m.key_used)
    models = Counter(m.model for m in answers if m.model)

    first_resp = [
        (aware(t.first_response_at) - aware(t.created_at)).total_seconds() / 3600
        for t in tickets
        if t.first_response_at
    ]
    breached = [t for t in open_tickets if aware(t.sla_due_at) < now]
    csat = [t.csat for t in tickets if t.csat]

    daily: dict[str, dict] = defaultdict(lambda: {"conversations": 0, "escalations": 0, "abstained": 0})
    for c in convs:
        daily[aware(c.created_at).date().isoformat()]["conversations"] += 1
    for t in tickets:
        daily[aware(t.created_at).date().isoformat()]["escalations"] += 1
    for m in answers:
        if m.abstained:
            daily[aware(m.created_at).date().isoformat()]["abstained"] += 1
    series = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        series.append({"date": d, **daily.get(d, {"conversations": 0, "escalations": 0, "abstained": 0})})

    def pct(a: float, b: float) -> float | None:
        return round(a / b, 4) if b else None

    return {
        "window_days": days,
        "conversations": len(convs),
        "questions": user_msgs,
        "answers": len(answers),
        "deflection_rate": pct(len(deflected), len(convs_with_answers)),
        "abstention_rate": pct(sum(1 for m in answers if m.abstained), len(answers)),
        "helpful_rate": pct(up, up + down),
        "feedback": {"up": up, "down": down},
        "latency_ms": {
            "p50": int(np.percentile(latencies, 50)) if latencies else None,
            "p95": int(np.percentile(latencies, 95)) if latencies else None,
        },
        "median_confidence": round(float(np.median(confs)), 4) if confs else None,
        "injection_flags": flagged,
        "tickets": {
            "created": len(tickets),
            "open_now": len(open_tickets),
            "sla_breached_now": len(breached),
            "by_category": dict(Counter(t.category for t in tickets)),
            "by_priority": dict(Counter(t.priority for t in tickets)),
            "triage_by_llm": sum(1 for t in tickets if t.triage_source == "llm"),
            "median_first_response_h": round(float(np.median(first_resp)), 2) if first_resp else None,
            "csat_avg": round(sum(csat) / len(csat), 2) if csat else None,
            "csat_count": len(csat),
        },
        "llm": {"keys": dict(keys), "models": dict(models)},
        "series": series,
        "kb": rag.index_stats(db),
    }


@router.post("/eval")
def trigger_eval(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    enforce(f"eval:{user.id}", 6, 3600)
    enforce("eval:global", 30, 3600)
    t0 = time.perf_counter()
    metrics = run_eval(db)
    run = EvalRun(
        triggered_by=user.id,
        kb_version=rag.kb_version(db),
        n_questions=metrics["n_answerable"] + metrics["n_out_of_scope"],
        metrics=metrics,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(run)
    audit(db, user, "eval.run", target=f"eval:{run.id}", ip=client_ip(request))
    db.commit()
    return {
        "id": run.id,
        "created_at": run.created_at,
        "kb_version": run.kb_version,
        "n_questions": run.n_questions,
        "duration_ms": run.duration_ms,
        "metrics": metrics,
    }


@router.get("/eval")
def list_evals(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    runs = db.scalars(select(EvalRun).order_by(EvalRun.id.desc()).limit(20)).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "kb_version": r.kb_version,
            "n_questions": r.n_questions,
            "duration_ms": r.duration_ms,
            "metrics": r.metrics,
        }
        for r in runs
    ]
