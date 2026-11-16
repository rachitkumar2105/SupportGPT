from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit, client_ip, get_current_user
from ..models import User, aware
from ..ratelimit import enforce
from ..schemas import ChangePasswordIn, LoginIn, SessionOut, SignupIn, UserOut
from ..security import (
    REFRESH_COOKIE,
    RefreshError,
    clear_session_cookies,
    create_access_token,
    hash_password,
    issue_refresh_token,
    password_problems,
    revoke_all_for_user,
    revoke_by_raw,
    rotate_refresh_token,
    set_session_cookies,
    verify_password,
)
from ..seed import DEMO_AGENT_EMAIL

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOCK_AFTER = 8
LOCK_MINUTES = 15


def _start_session(db: Session, user: User, request: Request, response: Response) -> SessionOut:
    user.last_login_at = datetime.now(UTC)
    refresh = issue_refresh_token(db, user, user_agent=request.headers.get("user-agent"))
    db.commit()
    csrf = set_session_cookies(response, create_access_token(user), refresh)
    return SessionOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/signup", response_model=SessionOut, status_code=201)
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    enforce(f"signup:{ip}", 5, 3600)
    email = body.email.lower()
    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try signing in.")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), role="customer")
    db.add(user)
    db.flush()
    audit(db, user, "auth.signup", target=f"user:{user.id}", ip=ip)
    return _start_session(db, user, request, response)


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    enforce(f"login-ip:{ip}", 10, 60)
    email = body.email.lower()
    enforce(f"login-acct:{email}", 20, 3600)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    now = datetime.now(UTC)

    if user and user.locked_until and aware(user.locked_until) > now:
        raise HTTPException(status_code=423, detail="Too many failed attempts. Try again in a few minutes.")

    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= LOCK_AFTER:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
                audit(db, user, "auth.locked", target=f"user:{user.id}", ip=ip)
            db.commit()
        raise HTTPException(status_code=401, detail="That email and password don't match.")

    user.failed_logins = 0
    user.locked_until = None
    audit(db, user, "auth.login", target=f"user:{user.id}", ip=ip)
    return _start_session(db, user, request, response)


@router.post("/demo-agent", response_model=SessionOut)
def demo_agent(request: Request, response: Response, db: Session = Depends(get_db)):
    """One-click entry to the agent console for portfolio visitors. No shared password
    exists; the account can only be entered through this rate-limited endpoint and is
    blocked from admin routes and destructive actions."""
    if not get_settings().demo_agent_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    ip = client_ip(request)
    enforce(f"demo:{ip}", 10, 3600)
    user = db.scalar(select(User).where(User.email == DEMO_AGENT_EMAIL))
    if user is None or not user.is_active:
        raise HTTPException(status_code=503, detail="The demo agent isn't available right now.")
    audit(db, user, "auth.demo_login", ip=ip)
    return _start_session(db, user, request, response)


@router.post("/refresh", response_model=SessionOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(f"refresh:{client_ip(request)}", 60, 60)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Not signed in.")
    try:
        user, new_raw = rotate_refresh_token(db, raw, request.headers.get("user-agent"))
    except RefreshError:
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.") from None
    db.commit()
    csrf = set_session_cookies(response, create_access_token(user), new_raw)
    return SessionOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_by_raw(db, request.cookies.get(REFRESH_COOKIE))
    db.commit()
    clear_session_cookies(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.is_demo:
        raise HTTPException(status_code=403, detail="The demo account's password can't be changed.")
    enforce(f"pwchange:{user.id}", 5, 3600)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    problems = password_problems(body.new_password, user.email)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # invalidates every outstanding access token
    revoke_all_for_user(db, user.id)  # and every refresh token (signs out other devices)
    audit(db, user, "auth.password_changed", target=f"user:{user.id}", ip=client_ip(request))
    db.commit()
    clear_session_cookies(response)
    response.status_code = 204
    return response
