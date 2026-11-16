from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal
from .routers import admin, auth, chat, kb, tickets
from .security import CSRF_COOKIE, csrf_ok
from .services import rag

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("supportgpt")

VERSION = "4.0.0"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Pre-session endpoints have no CSRF cookie yet; they rely on the Origin allowlist + SameSite cookies.
CSRF_EXEMPT = {"/api/auth/login", "/api/auth/signup", "/api/auth/demo-agent"}
MAX_BODY = 12 * 1024 * 1024
_state = {"ready": False, "error": None}

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")


def _warm_up() -> None:
    from .seed import run_all

    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        run_all(db)
        _state["ready"] = True
        log.info("ready in %.1fs", time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001
        _state["error"] = type(exc).__name__
        log.exception("warm-up failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().env == "test":
        _state["ready"] = True
    else:
        # Loading the ONNX model and seeding takes a few seconds; don't block the port.
        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


class GuardMiddleware:
    """Pure ASGI (streaming-safe) middleware: body cap, Origin allowlist, CSRF, security headers, access log."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope["method"]
        path = scope["path"]
        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope["headers"]}
        rid = uuid.uuid4().hex[:12]
        started = time.perf_counter()

        async def reject(status: int, detail: str):
            resp = JSONResponse({"detail": detail}, status_code=status)
            await resp(scope, receive, send_wrapper)

        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                hdrs = list(message.get("headers", []))
                hdrs.extend(SECURITY_HEADERS)
                hdrs.append((b"x-request-id", rid.encode()))
                if not path.startswith("/api/docs") and path != "/api/openapi.json":
                    hdrs.append(API_CSP)
                if path.startswith("/api") and not any(k == b"cache-control" for k, _ in hdrs):
                    hdrs.append((b"cache-control", b"no-store"))
                message["headers"] = hdrs
            await send(message)

        try:
            if path.startswith("/api") and method in UNSAFE:
                length = headers.get("content-length")
                if length and length.isdigit() and int(length) > MAX_BODY:
                    return await reject(413, "Request body is too large.")
                origin = headers.get("origin")
                if origin and origin.rstrip("/") not in get_settings().allowed_origins:
                    return await reject(403, "This origin isn't allowed to call the API.")
                if path not in CSRF_EXEMPT:
                    jar = SimpleCookie()
                    try:
                        jar.load(headers.get("cookie", ""))
                    except Exception:  # noqa: BLE001, S110 - malformed Cookie header => no CSRF cookie
                        pass
                    cookie = jar[CSRF_COOKIE].value if CSRF_COOKIE in jar else None
                    if not csrf_ok(cookie, headers.get("x-csrf-token")):
                        return await reject(
                            403, "Your session token is missing or stale. Refresh the page and try again."
                        )
            await self.app(scope, receive, send_wrapper)
        finally:
            if path != "/api/health":
                log.info(
                    "%s %s %s %dms rid=%s",
                    method,
                    path,
                    status_holder["code"],
                    int((time.perf_counter() - started) * 1000),
                    rid,
                )


app = FastAPI(
    title="SupportGPT API",
    version=VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.add_middleware(GuardMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
    msg = str(first.get("msg", "Invalid input.")).removeprefix("Value error, ")
    return JSONResponse(
        status_code=422,
        content={
            "detail": f"{field}: {msg}" if field != "request" else msg,
            "errors": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in errors],
        },
    )


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})


for r in (auth.router, chat.router, tickets.router, kb.router, admin.router):
    app.include_router(r)


@app.get("/", include_in_schema=False)
def root():
    return {"service": "SupportGPT API", "version": VERSION, "docs": "/api/docs", "health": "/api/health"}


@app.get("/api/public/quality", tags=["meta"])
def public_quality():
    """Latest retrieval-eval headline numbers for the landing page. Real measurements only:
    returns null until an eval has been run against the current deployment."""
    from sqlalchemy import select

    from .models import EvalRun

    with SessionLocal() as db:
        run = db.scalar(select(EvalRun).order_by(EvalRun.id.desc()).limit(1))
    if run is None:
        return {"latest": None}
    m = run.metrics
    return {
        "latest": {
            "created_at": run.created_at,
            "n_answerable": m["n_answerable"],
            "n_out_of_scope": m["n_out_of_scope"],
            "retrieval": m["retrieval"],
            "abstention": m["abstention"]["current"],
            "latency_ms": m["latency_ms"],
        }
    }


@app.get("/api/health", tags=["meta"])
def health():
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            stats = rag.index_stats(db) if _state["ready"] else None
    except Exception:  # noqa: BLE001
        db_ok, stats = False, None
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status": "ok" if db_ok and _state["ready"] else ("warming" if db_ok else "degraded"),
            "version": VERSION,
            "database": "ok" if db_ok else "unreachable",
            "ready": _state["ready"],
            "warmup_error": _state["error"],
            "kb": stats,
            "abstain_threshold": get_settings().abstain_threshold,
            "llm": "configured" if get_settings().groq_primary else "not configured",
            "llm_failover": bool(get_settings().groq_secondary),
        },
    )
