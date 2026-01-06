"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from whoop_coach.api.routes import router
from whoop_coach.bot.app import create_bot
from whoop_coach.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize and cleanup resources."""
    settings = get_settings()

    # Create and initialize PTB application
    tg_app = create_bot()
    await tg_app.initialize()
    await tg_app.start()
    app.state.tg_app = tg_app

    # Set webhook in production
    if settings.is_prod and settings.TELEGRAM_WEBHOOK_URL:
        await tg_app.bot.set_webhook(settings.TELEGRAM_WEBHOOK_URL)
        logger.info(f"Telegram webhook set to: {settings.TELEGRAM_WEBHOOK_URL}")
    else:
        logger.info(f"Webhook not set: is_prod={settings.is_prod}, url={settings.TELEGRAM_WEBHOOK_URL}")

    yield

    # Cleanup
    if settings.is_prod:
        await tg_app.bot.delete_webhook()
    await tg_app.stop()
    await tg_app.shutdown()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="WHOOP Coach",
        description="Telegram training assistant powered by WHOOP",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(router)

    return app
