"""Password hashing, JWT access tokens, rotating refresh tokens and CSRF.

Session model
-------------
* Access token: short-lived JWT (15 min) in an HttpOnly cookie. Carries the
  user's ``token_version`` so a password change or role change invalidates
  every outstanding access token immediately.
* Refresh token: opaque random string in an HttpOnly cookie scoped to
  ``/api/auth``. Only its SHA-256 hash is stored. Every refresh rotates it;
  presenting an already-rotated token is treated as theft and revokes the
  whole token family (all sessions descended from that login).
* CSRF: double-submit cookie. A non-HttpOnly ``sg_csrf`` cookie is mirrored by
  the SPA into an ``X-CSRF-Token`` header on unsafe methods. Combined with
  SameSite=Lax cookies and an Origin allowlist check.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import RefreshToken, User, aware

ACCESS_COOKIE = "sg_access"
REFRESH_COOKIE = "sg_refresh"
CSRF_COOKIE = "sg_csrf"
ALGORITHM = "HS256"

_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)  # OWASP 2023 minimum for argon2id
# Hash used to equalise timing when the email does not exist (prevents user enumeration by timing).
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _ph.verify(hashed or _DUMMY_HASH, password) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "ver": user.token_version,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_ttl_min),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        data = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError:
        return None
    return data if data.get("type") == "access" else None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_refresh_token(db: Session, user: User, family_id: str | None = None, user_agent: str | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or str(uuid.uuid4()),
            token_hash=_sha256(raw),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_ttl_days),
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    return raw


class RefreshError(Exception):
    pass


def rotate_refresh_token(db: Session, raw: str, user_agent: str | None = None) -> tuple[User, str]:
    """Validates and rotates a refresh token. Raises RefreshError on any failure."""
    now = datetime.now(UTC)
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw)))
    if rt is None:
        raise RefreshError("unknown token")
    if rt.revoked_at is not None:
        # Reuse of a rotated token: assume it was stolen and kill the whole family.
        revoke_family(db, rt.family_id)
        db.commit()
        raise RefreshError("token reuse detected")
    if aware(rt.expires_at) <= now:
        raise RefreshError("expired")
    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise RefreshError("inactive user")
    rt.revoked_at = now
    new_raw = issue_refresh_token(db, user, family_id=rt.family_id, user_agent=user_agent)
    return user, new_raw


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def revoke_by_raw(db: Session, raw: str | None) -> None:
    if not raw:
        return
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw)))
    if rt is not None:
        revoke_family(db, rt.family_id)


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def set_session_cookies(response: Response, access: str, refresh: str) -> str:
    s = get_settings()
    csrf = secrets.token_urlsafe(32)
    common = {"secure": s.cookie_secure, "samesite": "lax"}
    response.set_cookie(ACCESS_COOKIE, access, httponly=True, path="/api", max_age=s.access_ttl_min * 60, **common)
    response.set_cookie(
        REFRESH_COOKIE, refresh, httponly=True, path="/api/auth", max_age=s.refresh_ttl_days * 86400, **common
    )
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, path="/", max_age=s.refresh_ttl_days * 86400, **common)
    return csrf


def clear_session_cookies(response: Response) -> None:
    s = get_settings()
    for name, path in ((ACCESS_COOKIE, "/api"), (REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path, secure=s.cookie_secure, samesite="lax")


def csrf_ok(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "123456789",
    "1234567890",
    "qwerty123",
    "qwertyuiop",
    "iloveyou",
    "admin123",
    "welcome1",
    "letmein123",
    "abc123456",
    "passw0rd",
    "football1",
    "11111111",
    "12345678",
    "monkey123",
    "dragon123",
    "sunshine1",
    "princess1",
}


def password_problems(password: str, email: str = "") -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("Use at least 10 characters.")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("Mix letters and numbers.")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("This password is too common.")
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        problems.append("Don't include your email name in the password.")
    return problems
