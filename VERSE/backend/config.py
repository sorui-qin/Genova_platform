import os
from pathlib import Path
from urllib.parse import urlsplit


def validate_proxy_url(value):
    value = value.strip()
    try:
        url = urlsplit(value)
        if (len(value) > 2048 or url.scheme not in {"http", "https"} or not url.hostname
                or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or url.query or url.fragment
                or "\\" in value or "%" in url.hostname or any(ord(c) < 33 for c in value)
                or url.port == 0 or url.netloc.endswith(":")):
            raise ValueError()
        host = url.hostname.encode("idna").decode().lower()
        if ":" in host:
            host = f"[{host}]"
        return f"{url.scheme}://{host}:{url.port or (443 if url.scheme == 'https' else 80)}"
    except (ValueError, UnicodeError):
        raise ValueError("Use an HTTP(S) proxy URL without credentials, path, query or fragment") from None


def _as_bool(raw: str, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("BACKEND_APP_NAME", "Genova Backend")
        self.environment = os.getenv("BACKEND_ENV", "dev").strip().lower()
        self.api_prefix = "/api/v1"
        self.data_retention_enabled = _as_bool(os.getenv("DATA_RETENTION_ENABLED"), False)
        self.ecloudgen_full_target = _as_bool(os.getenv("ECLOUDGEN_FULL_TARGET"), True)

        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@postgres:5432/genova",
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.redis_dispatch_queue = os.getenv("REDIS_DISPATCH_QUEUE", "genova:queue:dispatch")
        self.redis_result_queue = os.getenv("REDIS_RESULT_QUEUE", "genova:queue:result")

        self.jwt_secret = os.getenv("JWT_SECRET", "change-me-in-prod")
        self.agent_proxy_allowed_urls = list(dict.fromkeys(validate_proxy_url(value)
            for value in os.getenv("AGENT_PROXY_ALLOWED_URLS", "").split(",") if value.strip()))
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        self.refresh_token_expire_days = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
        self.guest_code_expire_days = int(os.getenv("GUEST_CODE_EXPIRE_DAYS", "7"))

        # Password reset mail; links point at PUBLIC_BASE_URL, never at a request's Host header.
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", "").strip() or self.smtp_username

        self.data_root = Path(os.getenv("DATA_ROOT", "/app/data")).resolve()
        # Non-structure upload size per file, and each user's total uploaded dataset storage.
        self.upload_file_max_mb = int(os.getenv("UPLOAD_FILE_MAX_MB", "500"))
        self.user_storage_quota_mb = int(os.getenv("USER_STORAGE_QUOTA_MB", "5120"))
        # Guests are created without sign-up, so each gets a smaller share.
        self.guest_storage_quota_mb = int(os.getenv("GUEST_STORAGE_QUOTA_MB", "500"))
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.auto_create_tables = _as_bool(os.getenv("AUTO_CREATE_TABLES", "1"), True)
        self.outbox_batch_size = int(os.getenv("OUTBOX_BATCH_SIZE", "20"))
        self.outbox_max_attempts = int(os.getenv("OUTBOX_MAX_ATTEMPTS", "10"))
        self.worker_idle_sleep_seconds = float(os.getenv("WORKER_IDLE_SLEEP_SECONDS", "0.5"))
        self.result_brpop_timeout = int(os.getenv("RESULT_BRPOP_TIMEOUT", "2"))
        self.workflow_poll_seconds = float(os.getenv("WORKFLOW_POLL_SECONDS", "1"))

        # Production must retain evidence across process restarts.
        production = self.environment in {"prod", "production"}
        default_knowledge = "postgres" if production else "memory"
        self.knowledge_backend = os.getenv("KNOWLEDGE_BACKEND", default_knowledge).strip().lower()
        if self.knowledge_backend not in {"memory", "postgres", "none"}:
            raise ValueError("KNOWLEDGE_BACKEND must be memory, postgres, or none")
        if production and self.knowledge_backend != "postgres":
            raise ValueError("Production requires KNOWLEDGE_BACKEND=postgres")


settings = Settings()
