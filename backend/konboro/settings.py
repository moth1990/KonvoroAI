"""App settings from the environment (KONBORO_* variables, see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The demo tenant's owner from `make seed` (konboro.db.seed). Kept here as text so settings import nothing.
DEMO_DEV_USERS = "demo@konboro.local=tnt_01JD0DEM000000000000000000"


class Settings(BaseSettings):
    # The repo-root .env (the backend runs from backend/), then a backend/.env if there is one.
    model_config = SettingsConfigDict(env_prefix="KONBORO_", env_file=("../.env", ".env"), extra="ignore")

    env: Literal["local", "test", "production"] = "local"
    cors_origins: list[str] = ["http://localhost:5180", "http://127.0.0.1:5180"]

    # Dev login (S03 decision): a stand-in for Cognito until S29. The email must be in `dev_users`
    # (email=tenant_id pairs, comma separated: our "user pool", like Cognito's tenant_id attribute),
    # and every dev user shares one password.
    dev_login_enabled: bool = True
    dev_password: SecretStr | None = None
    dev_users: str = DEMO_DEV_USERS
    jwt_secret: SecretStr = SecretStr("local-dev-only-signing-key-not-a-secret")
    jwt_ttl_minutes: int = 12 * 60

    flag_cache_seconds: float = 30.0

    # S3 and SQS (12 §3). Locally the endpoints point at S3Mock and ElasticMQ (docker-compose.yml), which accept
    # any credentials; in AWS the endpoints are unset and the IAM role signs requests.
    aws_region: str = "eu-central-1"
    s3_endpoint: str | None = None
    sqs_endpoint: str | None = None
    # Tests and E2E give their queues a prefix, so a running `make dev` worker never takes their messages.
    sqs_queue_prefix: str = ""
    s3_bucket: str = "konboro-files"
    s3_sse: Literal["AES256", "aws:kms"] = "AES256"  # aws:kms with the tenant key in AWS (S29)
    # How long the worker waits on an empty queue, and how long a failed stage waits before its retry.
    worker_poll_seconds: int = 2
    stage_retry_seconds: int = 5

    @model_validator(mode="after")
    def _safe(self) -> "Settings":
        if self.env == "production" and self.dev_login_enabled:
            raise ValueError("dev login must be off in production (KONBORO_DEV_LOGIN_ENABLED=false)")
        if len(self.jwt_secret.get_secret_value().encode()) < 32:  # RFC 7518 §3.2 for HS256
            raise ValueError("KONBORO_JWT_SECRET must be at least 32 bytes")
        return self

    def dev_directory(self) -> dict[str, str]:
        """email (lowercase) -> tenant_id."""
        pairs = (item.split("=", 1) for item in self.dev_users.split(",") if "=" in item)
        return {email.strip().lower(): tenant.strip() for email, tenant in pairs}


@lru_cache
def get_settings() -> Settings:
    return Settings()
