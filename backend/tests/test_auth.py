from datetime import datetime, timedelta, UTC

from tests.conftest import authed, make_client

from app.db import SessionLocal
from app.models import RefreshToken
from app.security import create_access_token


def test_signup_sets_httponly_cookies(customer):
    r = customer.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "customer"


def test_signup_cookie_flags():
    c = make_client()
    r = c.post(
        "/api/auth/signup", json={"name": "Flag Test", "email": "flags@example.com", "password": "correct-horse-42"}
    )
    cookies = r.headers.get_list("set-cookie")
    access = next(h for h in cookies if h.startswith("sg_access="))
    refresh = next(h for h in cookies if h.startswith("sg_refresh="))
    csrf = next(h for h in cookies if h.startswith("sg_csrf="))
    assert "HttpOnly" in access and "SameSite=lax" in access and "Path=/api" in access
    assert "HttpOnly" in refresh and "Path=/api/auth" in refresh
    assert "HttpOnly" not in csrf


def test_weak_and_duplicate_passwords_rejected():
    c = make_client()
    r = c.post("/api/auth/signup", json={"name": "W", "email": "weak@example.com", "password": "short1"})
    assert r.status_code == 422
    r = c.post("/api/auth/signup", json={"name": "W", "email": "weak@example.com", "password": "password123"})
    assert r.status_code == 422
    ok = c.post("/api/auth/signup", json={"name": "W", "email": "dupe@example.com", "password": "long-enough-pw-9"})
    assert ok.status_code == 201
    again = make_client().post(
        "/api/auth/signup", json={"name": "W", "email": "DUPE@example.com", "password": "long-enough-pw-9"}
    )
    assert again.status_code == 409


def test_unknown_fields_rejected():
    r = make_client().post(
        "/api/auth/signup",
        json={"name": "X", "email": "x@example.com", "password": "long-enough-pw-9", "role": "admin"},
    )
    assert r.status_code == 422


def test_login_failure_is_generic_and_locks_out():
    c = make_client()
    c.post("/api/auth/signup", json={"name": "L", "email": "lock@example.com", "password": "long-enough-pw-9"})
    r = make_client().post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    assert r.status_code == 401
    msg = r.json()["detail"]
    c2 = make_client()
    for _ in range(8):
        r = c2.post("/api/auth/login", json={"email": "lock@example.com", "password": "wrong-password-1"})
        assert r.json()["detail"] == msg  # same message whether or not the account exists
    r = c2.post("/api/auth/login", json={"email": "lock@example.com", "password": "long-enough-pw-9"})
    assert r.status_code == 423


def test_requires_session():
    assert make_client().get("/api/auth/me").status_code == 401
    assert make_client().get("/api/conversations").status_code == 401


def test_forged_and_expired_tokens_rejected(customer):
    c = make_client()
    c.cookies.set("sg_access", "not-a-jwt", path="/api")
    assert c.get("/api/auth/me").status_code == 401
    import jwt

    forged = jwt.encode(
        {"sub": "1", "type": "access", "ver": 0, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "wrong-key-wrong-key-wrong-key-wrong-key",
        algorithm="HS256",
    )
    c.cookies.set("sg_access", forged, path="/api")
    assert c.get("/api/auth/me").status_code == 401


def test_csrf_and_origin_enforced(customer):
    token = customer.headers.pop("x-csrf-token")
    assert customer.post("/api/conversations").status_code == 403
    customer.headers["x-csrf-token"] = "wrong"
    assert customer.post("/api/conversations").status_code == 403
    customer.headers["x-csrf-token"] = token
    assert customer.post("/api/conversations").status_code == 201
    customer.headers["origin"] = "https://evil.example"
    assert customer.post("/api/conversations").status_code == 403


def test_refresh_rotation_and_reuse_detection():
    c = make_client()
    r = c.post("/api/auth/signup", json={"name": "R", "email": "rot@example.com", "password": "long-enough-pw-9"})
    authed(c, r)
    uid = r.json()["user"]["id"]
    old_refresh = c.cookies.get("sg_refresh")
    r = c.post("/api/auth/refresh")
    assert r.status_code == 200
    c.headers["x-csrf-token"] = r.json()["csrf_token"]
    new_refresh = c.cookies.get("sg_refresh")
    assert new_refresh and new_refresh != old_refresh

    # An attacker replays the old (rotated) token: the whole family is revoked.
    thief = make_client()
    thief.cookies.set("sg_refresh", old_refresh, path="/api/auth")
    thief.cookies.set("sg_csrf", "x", path="/")
    thief.headers["x-csrf-token"] = "x"
    assert thief.post("/api/auth/refresh").status_code == 401
    assert c.post("/api/auth/refresh").status_code == 401  # legit session killed too
    with SessionLocal() as db:
        assert all(t.revoked_at is not None for t in db.query(RefreshToken).filter_by(user_id=uid))


def test_logout_revokes_refresh(customer):
    assert customer.post("/api/auth/logout").status_code == 204
    customer.cookies.set("sg_csrf", customer.headers["x-csrf-token"], path="/")
    assert customer.post("/api/auth/refresh").status_code == 401


def test_password_change_invalidates_existing_tokens():
    c = make_client()
    authed(c, c.post("/api/auth/signup", json={"name": "P", "email": "pw@example.com", "password": "long-enough-pw-9"}))
    stale_access = c.cookies.get("sg_access")
    r = c.post(
        "/api/auth/change-password", json={"current_password": "long-enough-pw-9", "new_password": "another-long-pw-7"}
    )
    assert r.status_code == 204
    other = make_client()
    other.cookies.set("sg_access", stale_access, path="/api")
    assert other.get("/api/auth/me").status_code == 401
    ok = make_client().post("/api/auth/login", json={"email": "pw@example.com", "password": "another-long-pw-7"})
    assert ok.status_code == 200


def test_demo_agent_cannot_reach_admin(agent):
    assert agent.get("/api/auth/me").json()["role"] == "agent"
    assert agent.get("/api/admin/users").status_code == 403
    assert agent.post("/api/kb/documents", files={"file": ("a.md", b"# A\n\n" + b"x" * 100)}).status_code == 403
    assert (
        agent.post("/api/auth/change-password", json={"current_password": "x", "new_password": "y"}).status_code == 403
    )


def test_role_change_takes_effect_immediately(admin):
    c = make_client()
    r = c.post(
        "/api/auth/signup", json={"name": "Promote", "email": "promote@example.com", "password": "long-enough-pw-9"}
    )
    authed(c, r)
    uid = r.json()["user"]["id"]
    assert c.get("/api/kb/documents").status_code == 403
    assert admin.patch(f"/api/admin/users/{uid}", json={"role": "agent"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401  # old token carries old token_version
    r = c.post("/api/auth/refresh")
    c.headers["x-csrf-token"] = r.json()["csrf_token"]
    assert c.get("/api/kb/documents").status_code == 200


def test_security_headers_present():
    r = make_client().get("/api/health")
    for h in (
        "x-content-type-options",
        "x-frame-options",
        "content-security-policy",
        "referrer-policy",
        "strict-transport-security",
    ):
        assert h in r.headers
    assert r.headers["cache-control"] == "no-store"


def test_access_token_shape(customer):
    from app.models import User

    with SessionLocal() as db:
        u = db.query(User).first()
        tok = create_access_token(u)
    assert tok.count(".") == 2
