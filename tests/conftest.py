import os

os.environ.setdefault("SECRET_KEY", "test_secret_key_for_pytest")
os.environ.setdefault("GROQ_API_KEY_PRIMARY", "test_primary_key")
os.environ.setdefault("GROQ_API_KEY_SECONDARY", "test_secondary_key")
os.environ.setdefault("SEED_DEMO_USERS", "false")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_app.db")
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import numpy as np
import pytest
from fastapi.testclient import TestClient

import rag


def _fake_vector(text: str) -> np.ndarray:
    """Deterministic, dependency-free stand-in for a real embedding so tests
    don't need to download/run the ONNX embedding model."""
    rng = np.random.RandomState(abs(hash(text)) % (2 ** 32))
    vector = rng.rand(rag.EMBEDDING_DIM).astype("float32")
    return vector / np.linalg.norm(vector)


def _fake_embed_texts(texts):
    if not texts:
        return np.zeros((0, rag.EMBEDDING_DIM), dtype="float32")
    return np.stack([_fake_vector(t) for t in texts])


rag.embed_texts = _fake_embed_texts
rag.embed_query = lambda text: _fake_embed_texts([text])[0]

import app as app_module  # noqa: E402  (import after env + rag patch)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


@pytest.fixture(autouse=True)
def patch_groq(monkeypatch):
    def fake_create_completion(**kwargs):
        return _FakeCompletion("This is a mocked AI response."), "primary"
    monkeypatch.setattr(app_module.groq_client, "create_completion", fake_create_completion)


@pytest.fixture(scope="session")
def client():
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    def _make(username="testuser", password="Passw0rd!", email=None):
        client.post("/signup", json={"username": username, "password": password, "email": email})
        resp = client.post("/login", json={"username": username, "password": password})
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _make
