from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_url: str
    session_cookie_secure: bool
    session_cookie_http_only: bool
    session_cookie_samesite: str
    permanent_session_lifetime_minutes: int
    csrf_enabled: bool
    rate_limit_default: str
    auth_login_rate_limit: str
    write_rate_limit: str
    rate_limit_storage_uri: str | None
    monitoring_storage: str
    model_storage_backend: str

    @property
    def permanent_session_lifetime(self) -> timedelta:
        return timedelta(minutes=self.permanent_session_lifetime_minutes)


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    return Settings(
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///ipl_saas.db"),
        session_cookie_secure=_to_bool(os.getenv("SESSION_COOKIE_SECURE"), True),
        session_cookie_http_only=_to_bool(os.getenv("SESSION_COOKIE_HTTPONLY"), True),
        session_cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        permanent_session_lifetime_minutes=int(os.getenv("SESSION_TIMEOUT_MINUTES", "240")),
        csrf_enabled=_to_bool(os.getenv("CSRF_ENABLED"), True),
        rate_limit_default=os.getenv("RATE_LIMIT_DEFAULT", "200 per hour"),
        auth_login_rate_limit=os.getenv("AUTH_LOGIN_RATE_LIMIT", "10 per minute"),
        write_rate_limit=os.getenv("WRITE_RATE_LIMIT", "30 per minute"),
        rate_limit_storage_uri=(
            str(os.getenv("RATE_LIMIT_STORAGE_URI", "")).strip()
            or str(os.getenv("REDIS_URL", "")).strip()
            or None
        ),
        monitoring_storage=os.getenv("MONITORING_STORAGE", "database"),
        model_storage_backend=os.getenv("MODEL_STORAGE_BACKEND", "local"),
    )
