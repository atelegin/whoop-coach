"""Test configuration module."""

import pytest

from whoop_coach.config import Settings


def test_default_settings():
    """Test default settings values."""
    settings = Settings(TELEGRAM_BOT_TOKEN="test-token", _env_file=None)
    assert settings.ENV == "dev"
    assert settings.is_dev is True
    assert settings.is_prod is False


def test_prod_requires_webhook_url():
    """Test that prod mode requires TELEGRAM_WEBHOOK_URL."""
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_URL is required"):
        Settings(
            ENV="prod",
            TELEGRAM_BOT_TOKEN="test-token",
            SECRET_KEY="prod-secret",
            _env_file=None,
        )


def test_prod_requires_secret_key():
    """Test that prod mode requires non-default SECRET_KEY."""
    with pytest.raises(ValueError, match="SECRET_KEY must be changed"):
        Settings(
            ENV="prod",
            TELEGRAM_BOT_TOKEN="test-token",
            TELEGRAM_WEBHOOK_URL="https://example.com/webhooks/telegram",
            SECRET_KEY="dev-secret-key",
            _env_file=None,
        )


def test_prod_valid_settings():
    """Test valid prod settings."""
    settings = Settings(
        ENV="prod",
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_WEBHOOK_URL="https://example.com/webhooks/telegram",
        SECRET_KEY="prod-secret-key",
        _env_file=None,
    )
    assert settings.is_prod is True
    assert settings.is_dev is False

