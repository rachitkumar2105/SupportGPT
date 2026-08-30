"""Dual-key Groq client with automatic failover on rate-limit/quota exhaustion.

Both GROQ_API_KEY_PRIMARY and GROQ_API_KEY_SECONDARY are required. There is no
single-key fallback path: if either is missing, the app refuses to start.
"""
import os
from groq import Groq


class DualKeyGroqClient:
    def __init__(self):
        primary_key = os.environ.get("GROQ_API_KEY_PRIMARY")
        secondary_key = os.environ.get("GROQ_API_KEY_SECONDARY")
        if not primary_key or not secondary_key:
            raise RuntimeError(
                "Both GROQ_API_KEY_PRIMARY and GROQ_API_KEY_SECONDARY environment "
                "variables must be set. Refusing to start without both Groq API keys."
            )
        self._clients = {
            "primary": Groq(api_key=primary_key),
            "secondary": Groq(api_key=secondary_key),
        }

    @staticmethod
    def _is_quota_exhausted(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        message = str(exc).lower()
        return any(term in message for term in ("rate limit", "rate_limit", "quota"))

    def create_completion(self, **kwargs):
        """Calls chat.completions.create, failing over to the secondary key on
        quota/rate-limit exhaustion. Returns (response, key_name_used)."""
        try:
            response = self._clients["primary"].chat.completions.create(**kwargs)
            return response, "primary"
        except Exception as primary_exc:
            if not self._is_quota_exhausted(primary_exc):
                raise
            response = self._clients["secondary"].chat.completions.create(**kwargs)
            return response, "secondary"


groq_client = DualKeyGroqClient()
