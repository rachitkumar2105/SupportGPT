import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    {
        "APP_ENV": "test",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",  # gitleaks:allow (test-only dummy)
        "EMBEDDER": "hash",
        "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
        "COOKIE_SECURE": "false",
        "ALLOWED_ORIGINS": "http://testserver,https://support-gpt.vercel.app",
        "DEMO_AGENT_ENABLED": "true",
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "Adm1n-password-long",
        "ABSTAIN_THRESHOLD": "0.0",
        "GROQ_API_KEY_PRIMARY": "",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402
from app.seed import run_all  # noqa: E402
from app.services import llm, rag  # noqa: E402


class FakeGateway:
    """Stands in for Groq. Tests set .stream_text / .complete_text / .fail."""

    def __init__(self):
        self.stream_text = "Refunds for monthly plans are available within 14 days [1]."
        self.complete_text = '{"subject":"Double charge on renewal","summary":"Customer was charged twice.","category":"billing","priority":"high","sentiment":"negative"}'
        self.fail = False
        self.calls = []

    def stream(self, messages, models, meta, **kw):
        self.calls.append(("stream", messages))
        if self.fail:
            raise llm.LLMUnavailable("down")
        meta.model, meta.key = models[0], "primary"
        words = self.stream_text.split(" ")
        for i, w in enumerate(words):
            yield w + (" " if i < len(words) - 1 else "")

    def complete(self, messages, models, **kw):
        self.calls.append(("complete", messages))
        if self.fail:
            raise llm.LLMUnavailable("down")
        meta = llm.CallMeta(model=models[0], key="primary")
        return self.complete_text, meta


@pytest.fixture(scope="session", autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        run_all(db)
    yield


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    fake = FakeGateway()
    import app.routers.chat as chat_mod
    import app.services.assistant as asst

    monkeypatch.setattr(chat_mod, "gateway", fake)
    monkeypatch.setattr(asst, "gateway", fake)
    limiter.reset()
    return fake


def make_client() -> TestClient:
    return TestClient(app, headers={"origin": "http://testserver"})


def authed(c: TestClient, resp) -> TestClient:
    assert resp.status_code in (200, 201), resp.text
    c.headers["x-csrf-token"] = resp.json()["csrf_token"]
    return c


_counter = {"n": 0}


@pytest.fixture
def customer():
    _counter["n"] += 1
    c = make_client()
    r = c.post(
        "/api/auth/signup",
        json={"name": "Asha Rao", "email": f"asha{_counter['n']}@example.com", "password": "correct-horse-42"},
    )
    return authed(c, r)


@pytest.fixture
def admin():
    c = make_client()
    return authed(c, c.post("/api/auth/login", json={"email": "admin@example.com", "password": "Adm1n-password-long"}))


@pytest.fixture
def agent():
    c = make_client()
    return authed(c, c.post("/api/auth/demo-agent"))


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        ev = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((ev, data))
    return events


@pytest.fixture
def set_threshold():
    from app.config import get_settings

    s = get_settings()
    original = s.abstain_threshold

    def _set(v):
        object.__setattr__(s, "abstain_threshold", v)

    yield _set
    object.__setattr__(s, "abstain_threshold", original)


__all__ = ["rag", "make_client", "authed", "parse_sse"]
