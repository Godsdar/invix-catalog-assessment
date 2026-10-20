from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "catalog"
    bot_token: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")
    admin_ids: str = ""
    mini_app_url: str = "https://example.com"
    max_photo_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)
    db_pool_size: int = Field(default=5, ge=1, le=30)

    @field_validator("mini_app_url")
    @classmethod
    def https_url(cls, value: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise ValueError("MINI_APP_URL must be a public HTTPS URL")
        return value.rstrip("/")

    @property
    def admins(self) -> set[int]:
        return {int(value.strip()) for value in self.admin_ids.split(",") if value.strip()}

    def require_bot(self) -> None:
        import re

        if not self.bot_token.get_secret_value():
            raise ValueError("BOT_TOKEN is required for bot and worker")
        secret = self.webhook_secret.get_secret_value()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
            raise ValueError("WEBHOOK_SECRET must have 32–256 URL-safe characters")
        if not self.admins:
            raise ValueError("ADMIN_IDS must contain at least one Telegram user id")


@lru_cache
def get_settings() -> Settings:
    return Settings()
