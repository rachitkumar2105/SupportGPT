"""Runtime configuration, read once from the environment.

The app refuses to start without the secrets it needs: there are no insecure
fallbacks (no default SECRET_KEY, no wildcard CORS).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    return [v.strip().rstrip("/") for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    database_url: str
    allowed_origins: list[str]
    cookie_secure: bool
    access_ttl_min: int
    refresh_ttl_days: int
    groq_primary: str
    groq_secondary: str
    answer_models: list[str]
    triage_models: list[str]
    embedder: str
    abstain_threshold: float
    admin_email: str | None
    admin_password: str | None
    demo_agent_enabled: bool
    seed_kb: bool
    max_upload_bytes: int = 10 * 1024 * 1024
    trusted_proxy_hops: int = 2
    extra: dict = field(default_factory=dict)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _normalise_db_url(url: str) -> str:
    # Neon/Heroku style URLs use postgres:// or postgresql://; SQLAlchemy needs a driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get("APP_ENV", "production")
    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("SECRET_KEY must be set and at least 32 characters long.")

    origins = _list("ALLOWED_ORIGINS", "http://localhost:5173")
    if any(o == "*" for o in origins):
        raise RuntimeError("ALLOWED_ORIGINS cannot contain '*' (credentials are sent with requests).")

    embedder = os.environ.get("EMBEDDER", "fastembed")
    # GROQ_API_KEY is accepted as the primary key for older deployments. Without any key the
    # service still starts: answers degrade to "talk to a person" and triage uses keyword rules.
    primary = os.environ.get("GROQ_API_KEY_PRIMARY") or os.environ.get("GROQ_API_KEY", "")
    secondary = os.environ.get("GROQ_API_KEY_SECONDARY", "")

    return Settings(
        env=env,
        secret_key=secret,
        database_url=_normalise_db_url(os.environ.get("DATABASE_URL", "sqlite:///./supportgpt.db")),
        allowed_origins=origins,
        cookie_secure=_bool("COOKIE_SECURE", True),
        access_ttl_min=int(os.environ.get("ACCESS_TOKEN_TTL_MIN", "15")),
        refresh_ttl_days=int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "7")),
        groq_primary=primary,
        groq_secondary=secondary,
        answer_models=_list("ANSWER_MODELS", "openai/gpt-oss-120b,llama-3.3-70b-versatile"),
        triage_models=_list("TRIAGE_MODELS", "openai/gpt-oss-20b,llama-3.1-8b-instant"),
        embedder=embedder,
        abstain_threshold=float(os.environ.get("ABSTAIN_THRESHOLD", "0.57")),
        admin_email=os.environ.get("ADMIN_EMAIL") or None,
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
        demo_agent_enabled=_bool("DEMO_AGENT_ENABLED", False),
        seed_kb=_bool("SEED_KB", True),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        trusted_proxy_hops=int(os.environ.get("TRUSTED_PROXY_HOPS", "2")),
    )
