"""Telegram bot application builder."""

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from whoop_coach.bot.handlers import (
    disconnect_command,
    gear_callback,
    gear_command,
    help_command,
    kb_swing_callback,
    kb_weight_callback,
    last_command,
    morning_command,
    pain_done_callback,
    pain_location_callback,
    plan_command,
    retry_callback,
    retry_command,
    rpe_callback,
    soreness_callback,
    start_command,
    unattributed_rpe_callback,
    undo_command,
    whoop_command,
    workout_select_callback,
    youtube_message_handler,
)
from whoop_coach.config import get_settings


def create_bot() -> Application:
    """Build and configure the PTB Application."""
    settings = get_settings()

    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("gear", gear_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("whoop", whoop_command))
    application.add_handler(CommandHandler("disconnect", disconnect_command))
    application.add_handler(CommandHandler("last", last_command))
    application.add_handler(CommandHandler("retry", retry_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("morning", morning_command))

    # Register callback handlers
    application.add_handler(
        CallbackQueryHandler(gear_callback, pattern=r"^gear:")
    )
    application.add_handler(
        CallbackQueryHandler(workout_select_callback, pattern=r"^workout_select:")
    )
    application.add_handler(
        CallbackQueryHandler(rpe_callback, pattern=r"^rpe:")
    )
    application.add_handler(
        CallbackQueryHandler(kb_weight_callback, pattern=r"^kb_weight:")
    )
    application.add_handler(
        CallbackQueryHandler(kb_swing_callback, pattern=r"^kb_swing:")
    )
    application.add_handler(
        CallbackQueryHandler(retry_callback, pattern=r"^retry:")
    )
    # Stage 3: Smart Questions callbacks
    application.add_handler(
        CallbackQueryHandler(soreness_callback, pattern=r"^soreness:")
    )
    application.add_handler(
        CallbackQueryHandler(pain_location_callback, pattern=r"^pain:")
    )
    application.add_handler(
        CallbackQueryHandler(pain_done_callback, pattern=r"^pain_done:")
    )
    application.add_handler(
        CallbackQueryHandler(unattributed_rpe_callback, pattern=r"^unattr_rpe:")
    )

    # Register message handler for YouTube URLs (must be last)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            youtube_message_handler,
        )
    )

    return application
