"""WHOOP webhook background processor."""

import uuid
from datetime import UTC, datetime

from whoop_coach.bot.handlers import get_whoop_client_with_refresh
from whoop_coach.db.models import WebhookEvent, WebhookEventStatus
from whoop_coach.db.session import async_session_factory


async def process_recovery_webhook(event_id: uuid.UUID, app) -> None:
    """Background: fetch recovery → check morning feedback → send plan.
    
    Called from routes.py via BackgroundTasks.
    """
    async with async_session_factory() as session:
        event = await session.get(WebhookEvent, event_id)
        if not event:
            return
        
        event.status = WebhookEventStatus.PROCESSING
        await session.commit()
        
        try:
            # Import User here to avoid circular imports
            from whoop_coach.db.models import User
            user = await session.get(User, event.user_id)
            if not user or not user.whoop_tokens_enc:
                event.status = WebhookEventStatus.FAILED
                event.error_message = "User not found or no tokens"
                await session.commit()
                return
            
            # Get WHOOP client with token refresh
            client, tokens_refreshed = await get_whoop_client_with_refresh(
                user.id, user.whoop_tokens_enc
            )
            
            try:
                # 1. Sleep → cycle_id + timezone_offset
                sleep = await client.get_sleep(event.sleep_id)
                cycle_id = sleep.get("cycle_id")
                tz_offset = sleep.get("timezone_offset", "+01:00")
                
                if not cycle_id:
                    event.status = WebhookEventStatus.FAILED
                    event.error_message = "No cycle_id in sleep data"
                    await session.commit()
                    return
                
                # 2. Recovery for cycle
                recovery = await client.get_recovery(cycle_id)
                if not recovery:
                    event.status = WebhookEventStatus.PENDING_SCORE
                    await session.commit()
                    return
                
                score_state = recovery.get("score_state", "")
                if score_state != "SCORED":
                    # Recovery not ready yet, wait for next webhook
                    event.status = WebhookEventStatus.PENDING_SCORE
                    await session.commit()
                    return
                
                # 3. Check if morning feedback needed first
                from whoop_coach.bot.handlers import _needs_morning_prompt
                needs_feedback = await _needs_morning_prompt(session, user.id)
                
                if needs_feedback:
                    # Send morning questions first
                    from whoop_coach.bot.keyboards import soreness_keyboard
                    from whoop_coach.bot.handlers import _get_berlin_date
                    
                    bot = app.state.tg_app.bot
                    today_str = _get_berlin_date().isoformat()
                    
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text="☀️ Доброе утро! Как ощущения после вчерашнего дня?",
                        reply_markup=soreness_keyboard(today_str),
                    )
                    
                    event.status = WebhookEventStatus.AWAITING_FEEDBACK
                    await session.commit()
                    return
                
                # 4. Generate and send plan
                # TODO: Implement planner module
                recovery_score = recovery.get("score", {}).get("recovery_score", 0)
                
                bot = app.state.tg_app.bot
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"☀️ Доброе утро! Recovery: {recovery_score}%\n\n"
                        f"🏃 План на сегодня: скоро будет готов.\n"
                        f"(planner module in progress)"
                    ),
                )
                
                event.status = WebhookEventStatus.DONE
                event.processed_at = datetime.now(UTC)
                await session.commit()
                
            finally:
                await client.close()
                
        except Exception as e:
            event.status = WebhookEventStatus.FAILED
            event.error_message = str(e)[:500]
            await session.commit()
            raise
