"""Groq access with two layers of resilience.

1. Key failover: a 429 / quota error on the primary key retries the same call
   on the secondary key. Auth or validation errors do not fail over.
2. Model fallback: if a model has been decommissioned or is unknown (Groq
   retires model IDs regularly; llama-3.3-70b-versatile went away in 2026),
   the next model in the configured list is tried.

Every call reports which model and key actually served it, so the analytics
page shows real failover counts rather than assumed ones.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..config import get_settings

log = logging.getLogger("supportgpt.llm")


class LLMUnavailable(Exception):
    pass


@dataclass
class CallMeta:
    model: str | None = None
    key: str | None = None
    attempts: list[str] = field(default_factory=list)


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


def _is_quota(exc: Exception) -> bool:
    if _status(exc) == 429:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "rate_limit" in msg or "quota" in msg


def _is_model_gone(exc: Exception) -> bool:
    msg = str(exc).lower()
    return _status(exc) in (400, 404) and (
        "model" in msg
        and ("decommission" in msg or "not found" in msg or "does not exist" in msg or "not exist" in msg)
    )


class GroqGateway:
    def __init__(self) -> None:
        self._clients: dict[str, object] | None = None
        self._lock = threading.Lock()

    def _get_clients(self) -> dict[str, object]:
        if self._clients is None:
            with self._lock:
                if self._clients is None:
                    from groq import Groq

                    s = get_settings()
                    if not s.groq_primary:
                        raise LLMUnavailable("No Groq API key is configured.")
                    clients = {"primary": Groq(api_key=s.groq_primary, timeout=60.0, max_retries=0)}
                    if s.groq_secondary:
                        clients["secondary"] = Groq(api_key=s.groq_secondary, timeout=60.0, max_retries=0)
                    self._clients = clients
        return self._clients

    def configured(self) -> bool:
        return bool(get_settings().groq_primary)

    def _call(self, models: list[str], meta: CallMeta, **kwargs):
        clients = self._get_clients()
        last_exc: Exception | None = None
        for model in models:
            for key_name, client in clients.items():
                meta.attempts.append(f"{model}@{key_name}")
                try:
                    result = client.chat.completions.create(model=model, **kwargs)
                    meta.model, meta.key = model, key_name
                    return result
                except Exception as exc:  # noqa: BLE001 - classified below
                    last_exc = exc
                    if _is_quota(exc):
                        log.warning("Groq quota/rate limit on %s key for %s; failing over", key_name, model)
                        continue  # try next key with same model
                    if _is_model_gone(exc):
                        log.warning("Groq model %s unavailable: %s", model, exc)
                        break  # next model
                    log.error("Groq call failed (%s@%s): %s", model, key_name, exc)
                    raise LLMUnavailable("The language model is unavailable right now.") from exc
        raise LLMUnavailable("All configured models and keys are exhausted.") from last_exc

    def complete(
        self,
        messages: list[dict],
        models: list[str],
        *,
        json_mode: bool = False,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> tuple[str, CallMeta]:
        meta = CallMeta()
        kwargs: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._call(models, meta, **kwargs)
        return (resp.choices[0].message.content or "").strip(), meta

    def stream(
        self,
        messages: list[dict],
        models: list[str],
        meta: CallMeta,
        *,
        max_tokens: int = 900,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        resp = self._call(models, meta, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True)
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text


gateway = GroqGateway()
