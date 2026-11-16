"""Startup seeding: admin account, demo agent, help-center articles, sample tickets.

Everything here is idempotent, so it runs on every boot.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SLA_HOURS, Document, Ticket, TicketMessage, User
from ..security import hash_password
from ..services import rag
from ..services.ingest import ingest

log = logging.getLogger("supportgpt.seed")
KB_DIR = Path(__file__).resolve().parent / "kb"
DEMO_AGENT_EMAIL = "demo.agent@supportgpt.demo"
SAMPLE_CUSTOMER_EMAIL = "sample.customer@supportgpt.demo"

SAMPLE_TICKETS = [
    {
        "subject": "Charged twice for my Plus renewal",
        "body": "Hi, my card shows two charges of $60 for the annual Plus renewal on the same day. "
        "Both look settled, not pending. Can you refund one of them?",
        "category": "billing",
        "priority": "high",
        "sentiment": "negative",
        "age_h": 2,
        "summary": "Customer reports two settled $60 charges for the same annual Plus renewal and asks for "
        "the duplicate to be refunded. Card details were not shared.",
    },
    {
        "subject": "Lost my phone with the authenticator app",
        "body": "I lost my phone and with it my authenticator app. I don't think I saved the recovery codes. "
        "How do I get back into my account?",
        "category": "account",
        "priority": "urgent",
        "sentiment": "neutral",
        "age_h": 0.5,
        "summary": "Customer lost the device holding their 2FA authenticator and likely has no recovery codes. "
        "Needs the identity-verification path for 2FA removal.",
    },
    {
        "subject": "Third laptop won't sync on Free plan",
        "body": "I signed in on my new work laptop but nothing syncs. It works on my phone and my home laptop.",
        "category": "technical",
        "priority": "medium",
        "sentiment": "neutral",
        "age_h": 20,
        "summary": "Free-plan customer added a third device that signs in but does not sync. Likely the two-device "
        "limit on Free.",
    },
]


def _title_from_markdown(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else fallback


def seed_users(db: Session) -> None:
    s = get_settings()
    if s.admin_email and s.admin_password:
        email = s.admin_email.lower()
        if db.scalar(select(User.id).where(User.email == email)) is None:
            db.add(User(email=email, name="Admin", role="admin", password_hash=hash_password(s.admin_password)))
            log.info("created admin account")
    if s.demo_agent_enabled and db.scalar(select(User.id).where(User.email == DEMO_AGENT_EMAIL)) is None:
        # Password nobody knows: the account is only reachable through POST /api/auth/demo-agent.
        db.add(
            User(
                email=DEMO_AGENT_EMAIL,
                name="Demo Agent",
                role="agent",
                is_demo=True,
                password_hash=hash_password(secrets.token_urlsafe(32)),
            )
        )
    db.commit()


def seed_kb(db: Session) -> int:
    added = 0
    existing = set(db.scalars(select(Document.slug).where(Document.source == "seed")).all())
    for path in sorted(KB_DIR.glob("*.md")):
        if path.stem in existing:
            continue
        data = path.read_bytes()
        title = _title_from_markdown(data.decode("utf-8"), path.stem.replace("-", " ").title())
        doc = ingest(db, title=title, data=data, source="seed", uploader=None, mime="text/markdown")
        doc.slug = path.stem  # stable slug: the eval golden set refers to it
        added += 1
    if added:
        db.commit()
    return added


def seed_sample_tickets(db: Session) -> None:
    """A few clearly labelled sample tickets so the demo agent console isn't empty.
    They belong to a demo customer and are excluded from analytics."""
    if not get_settings().demo_agent_enabled:
        return
    customer = db.scalar(select(User).where(User.email == SAMPLE_CUSTOMER_EMAIL))
    if customer is None:
        customer = User(
            email=SAMPLE_CUSTOMER_EMAIL,
            name="Sample Customer",
            role="customer",
            is_demo=True,
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(customer)
        db.flush()
    open_samples = db.scalar(
        select(Ticket.id).where(Ticket.customer_id == customer.id, Ticket.status.in_(("open", "pending")))
    )
    if open_samples:
        return
    now = datetime.now(UTC)
    for t in SAMPLE_TICKETS:
        created = now - timedelta(hours=t["age_h"])
        ticket = Ticket(
            customer_id=customer.id,
            subject=t["subject"],
            summary=t["summary"],
            category=t["category"],
            priority=t["priority"],
            sentiment=t["sentiment"],
            triage_source="sample",
            status="open",
            created_at=created,
            updated_at=created,
            sla_due_at=created + timedelta(hours=SLA_HOURS[t["priority"]]),
        )
        db.add(ticket)
        db.flush()
        db.add(
            TicketMessage(
                ticket_id=ticket.id, author_id=customer.id, kind="customer", body=t["body"], created_at=created
            )
        )
    db.commit()


def ensure_eval(db: Session) -> None:
    """Run the retrieval eval once per KB version so the public quality numbers always
    describe the index that is actually serving (the free Space's disk resets on restart)."""
    import time

    from ..models import EvalRun
    from ..services.evaluation import run_eval

    version = rag.kb_version(db)
    if db.scalar(select(EvalRun.id).where(EvalRun.kb_version == version)) is not None:
        return
    t0 = time.perf_counter()
    metrics = run_eval(db)
    db.add(
        EvalRun(
            triggered_by=None,
            kb_version=version,
            n_questions=metrics["n_answerable"] + metrics["n_out_of_scope"],
            metrics=metrics,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    )
    db.commit()
    log.info("startup eval: hybrid hit@1=%s", metrics["retrieval"]["hybrid"]["hit@1"])


def run_all(db: Session) -> None:
    seed_users(db)
    if get_settings().seed_kb:
        n = seed_kb(db)
        if n:
            log.info("seeded %d help-center articles", n)
    seed_sample_tickets(db)
    rag.search(db, "warm up", k=1)  # builds the in-process index once
    if get_settings().env != "test":
        ensure_eval(db)
