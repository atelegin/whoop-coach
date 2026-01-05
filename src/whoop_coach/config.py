"""Application configuration via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENV: Literal["dev", "prod"] = "dev"

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_URL: str | None = None

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"

    # WHOOP OAuth
    WHOOP_CLIENT_ID: str = ""
    WHOOP_CLIENT_SECRET: str = ""
    WHOOP_REDIRECT_URI: str = ""

    # WHOOP Webhook
    WHOOP_WEBHOOK_SECRET: str = ""

    # App secret
    SECRET_KEY: str = "dev-secret-key"

    @model_validator(mode="after")
    def validate_prod_settings(self) -> "Settings":
        """Ensure required settings are present in production."""
        if self.ENV == "prod":
            if not self.TELEGRAM_WEBHOOK_URL:
                raise ValueError("TELEGRAM_WEBHOOK_URL is required in prod")
            if self.SECRET_KEY == "dev-secret-key":
                raise ValueError("SECRET_KEY must be changed in prod")
        return self

    @property
    def is_dev(self) -> bool:
        return self.ENV == "dev"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
