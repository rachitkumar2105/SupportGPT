"""Exercises groq_client.DualKeyGroqClient directly. A genuine live 429 from
Groq can't be forced on demand, so this simulates the exact exception shape
(status_code=429) the real Groq SDK raises for rate-limit/quota errors."""
import os

os.environ.setdefault("GROQ_API_KEY_PRIMARY", "test_primary_key")
os.environ.setdefault("GROQ_API_KEY_SECONDARY", "test_secondary_key")

from groq_client import DualKeyGroqClient


class _Fake429(Exception):
    status_code = 429


class _FakeAuthError(Exception):
    status_code = 401


def _stub_chat(client_key_holder, fn):
    return type("X", (), {"completions": type("Y", (), {"create": staticmethod(fn)})()})()


def test_failover_triggers_on_429_from_primary():
    client = DualKeyGroqClient()
    calls = []

    def primary_create(**kwargs):
        calls.append("primary")
        raise _Fake429("rate limit exceeded")

    def secondary_create(**kwargs):
        calls.append("secondary")
        return "SECONDARY_RESPONSE"

    client._clients["primary"].chat = _stub_chat("primary", primary_create)
    client._clients["secondary"].chat = _stub_chat("secondary", secondary_create)

    response, key_used = client.create_completion(model="x", messages=[])

    assert calls == ["primary", "secondary"]
    assert key_used == "secondary"
    assert response == "SECONDARY_RESPONSE"


def test_no_failover_on_non_quota_error():
    client = DualKeyGroqClient()
    calls = []

    def primary_create(**kwargs):
        calls.append("primary")
        raise _FakeAuthError("invalid api key")

    def secondary_create(**kwargs):
        calls.append("secondary")
        return "SHOULD_NOT_BE_CALLED"

    client._clients["primary"].chat = _stub_chat("primary", primary_create)
    client._clients["secondary"].chat = _stub_chat("secondary", secondary_create)

    try:
        client.create_completion(model="x", messages=[])
        assert False, "expected _FakeAuthError to propagate"
    except _FakeAuthError:
        pass

    assert calls == ["primary"]


def test_primary_success_never_touches_secondary():
    client = DualKeyGroqClient()
    calls = []

    def primary_create(**kwargs):
        calls.append("primary")
        return "PRIMARY_RESPONSE"

    def secondary_create(**kwargs):
        calls.append("secondary")
        return "SHOULD_NOT_BE_CALLED"

    client._clients["primary"].chat = _stub_chat("primary", primary_create)
    client._clients["secondary"].chat = _stub_chat("secondary", secondary_create)

    response, key_used = client.create_completion(model="x", messages=[])

    assert calls == ["primary"]
    assert key_used == "primary"
    assert response == "PRIMARY_RESPONSE"
