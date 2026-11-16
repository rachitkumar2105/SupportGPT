from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User
from .security import ACCESS_COOKIE, decode_access_token


def client_ip(request: Request) -> str:
    """Best-effort client IP behind Vercel -> Hugging Face proxies.

    X-Forwarded-For is appended to by each proxy. We trust the configured
    number of hops counted from the right, so a client-supplied XFF prefix is
    ignored when traffic arrives through the expected proxy chain.
    """
    xff = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if parts:
        idx = max(0, len(parts) - get_settings().trusted_proxy_hops)
        return parts[idx][:64]
    return (request.client.host if request.client else "unknown")[:64]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    data = decode_access_token(token) if token else None
    if not data:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user = db.get(User, int(data["sub"]))
    if user is None or not user.is_active or user.token_version != data.get("ver"):
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You don't have access to this area.")
        return user

    return _dep


require_staff = require_roles("agent", "admin")
require_admin = require_roles("admin")


def audit(
    db: Session,
    actor: User | None,
    action: str,
    target: str | None = None,
    meta: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target=target, meta=meta, ip=ip))
