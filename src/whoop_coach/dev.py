"""Development entrypoint — runs bot in polling mode."""

import logging

from whoop_coach.bot.app import create_bot
from whoop_coach.config import get_settings
from whoop_coach.db.models import Base
from whoop_coach.db.session import engine


def main() -> None:
    """Run the bot in polling mode for local development."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger(__name__)

    settings = get_settings()
    logger.info(f"Starting in {settings.ENV} mode")

    # Build application
    application = create_bot()

    # Create tables on startup (dev only — production uses Alembic)
    async def on_startup(_):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    application.post_init = on_startup

    # Run bot in polling mode
    logger.info("Starting bot in polling mode...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
