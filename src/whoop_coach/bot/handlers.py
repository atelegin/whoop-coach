"""Telegram bot command and callback handlers."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from whoop_coach.bot.keyboards import (
    EQUIPMENT_LABELS,
    PAIN_LOCATIONS,
    equipment_keyboard,
    kb_weight_keyboard,
    pain_locations_keyboard,
    retry_keyboard,
    rpe_keyboard,
    soreness_keyboard,
    unattributed_rpe_keyboard,
    workout_candidates_keyboard,
)
from whoop_coach.config import get_settings
from whoop_coach.crypto import decrypt_tokens, encrypt_tokens
from whoop_coach.db.models import (
    EquipmentProfile,
    Feedback,
    PendingLog,
    PendingLogState,
    User,
    Video,
)
from whoop_coach.db.session import async_session_factory
from whoop_coach.matching import match_workout
from whoop_coach.whoop.client import WhoopClient
from whoop_coach.youtube import parse_youtube_url

import httpx


async def get_whoop_client_with_refresh(
    user_id: uuid.UUID, tokens_enc: str
) -> tuple[WhoopClient, bool]:
    """Get WHOOP client, refreshing tokens if needed.

    Returns:
        Tuple of (WhoopClient, tokens_were_refreshed)
    """
    tokens = decrypt_tokens(tokens_enc)
    client = WhoopClient(access_token=tokens.get("access_token"))

    # Test if token works by making a simple request
    try:
        await client.get_profile()
        return client, False
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 401:
            raise

    # Token expired — refresh
    await client.close()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh token available")

    client = WhoopClient()
    new_tokens = await client.refresh_tokens(refresh_token)
    client.access_token = new_tokens.access_token

    # Save new tokens to DB
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if user:
                user.whoop_tokens_enc = encrypt_tokens(new_tokens.to_dict())

    return client, True


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    """Get existing user or create a new one."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
    return user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command — greet user and ensure they exist in DB."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    name = update.effective_user.first_name or "друг"

    async with async_session_factory() as session:
        async with session.begin():
            await get_or_create_user(session, telegram_id)

    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        "Я твой персональный тренировочный ассистент на базе WHOOP.\n\n"
        "Используй /whoop чтобы подключить аккаунт.\n"
        "Используй /gear чтобы указать доступный инвентарь.\n"
        "Используй /help для списка команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command — show available commands."""
    if not update.message:
        return

    await update.message.reply_text(
        "📋 *Команды:*\n\n"
        "/start — начать\n"
        "/whoop — подключить WHOOP\n"
        "/disconnect — отключить WHOOP\n"
        "/last — последние данные\n"
        "/gear — выбрать инвентарь\n"
        "/plan — план на сегодня\n"
        "/morning — утренний опрос\n"
        "/help — эта справка",
        parse_mode="Markdown",
    )


async def disconnect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /disconnect command — clear WHOOP tokens."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user and user.whoop_tokens_enc:
                user.whoop_tokens_enc = None
                user.whoop_user_id = None
                await update.message.reply_text(
                    "✅ WHOOP отключен.\n\n"
                    "Используй /whoop для повторного подключения."
                )
            else:
                await update.message.reply_text(
                    "ℹ️ WHOOP не был подключен."
                )


async def gear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gear command — show current equipment and selection buttons."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            current = user.equipment_profile

    label = EQUIPMENT_LABELS[current]
    await update.message.reply_text(
        f"🎒 *Сейчас:* {label}\n\nВыбери режим:",
        parse_mode="Markdown",
        reply_markup=equipment_keyboard(current),
    )


async def gear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle equipment selection callback."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    # Parse callback data: "gear:home_full"
    _, profile_value = query.data.split(":", 1)
    try:
        new_profile = EquipmentProfile(profile_value)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            user.equipment_profile = new_profile

    label = EQUIPMENT_LABELS[new_profile]
    await query.edit_message_text(
        f"✅ Ок, режим: {label}",
        reply_markup=equipment_keyboard(new_profile),
    )


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /plan command — placeholder for now."""
    if not update.message:
        return

    await update.message.reply_text(
        "🚧 *План пока недоступен*\n\n"
        "Сначала нужно подключить WHOOP аккаунт.",
        parse_mode="Markdown",
    )


async def whoop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /whoop command — show WHOOP connection status and link."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    settings = get_settings()

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            is_connected = user.whoop_tokens_enc is not None

    if is_connected:
        await update.message.reply_text(
            "✅ *WHOOP подключен*\n\n"
            "Используй /last для просмотра данных.",
            parse_mode="Markdown",
        )
    else:
        # Build OAuth link
        base_url = settings.WHOOP_REDIRECT_URI.rsplit("/callback", 1)[0]
        auth_url = f"{base_url}?{urlencode({'telegram_id': telegram_id})}"

        # Note: Telegram rejects localhost URLs in inline buttons,
        # so we show the link as text for dev mode
        await update.message.reply_text(
            f"⚠️ WHOOP не подключен\n\n"
            f"Открой ссылку для авторизации:\n{auth_url}",
        )


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /last command — show recent WHOOP data."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            tokens_enc = user.whoop_tokens_enc

    if not tokens_enc:
        await update.message.reply_text(
            "⚠️ *WHOOP не подключен*\n\n"
            "Используй /whoop для подключения.",
            parse_mode="Markdown",
        )
        return

    # Decrypt tokens
    tokens = decrypt_tokens(tokens_enc)
    access_token = tokens.get("access_token")

    # Fetch data from WHOOP
    client = WhoopClient(access_token=access_token)
    try:
        # Get current cycle
        cycles = await client.get_cycles(limit=1)
        cycle = cycles[0] if cycles else None

        # Get recovery for cycle
        recovery = None
        if cycle:
            cycle_id = cycle.get("id")
            if cycle_id:
                recovery = await client.get_recovery(cycle_id)

        # Get recent workouts
        workouts = await client.get_workouts(limit=3)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при получении данных: {e}\n\n"
            "Попробуй переподключить /whoop",
        )
        return
    finally:
        await client.close()

    # Format response
    lines = ["📊 *Последние данные WHOOP*\n"]

    # Recovery
    if recovery:
        score = recovery.get("score", {}).get("recovery_score", "—")
        hrv = recovery.get("score", {}).get("hrv_rmssd_milli", 0)
        rhr = recovery.get("score", {}).get("resting_heart_rate", 0)
        lines.append(f"💚 *Recovery:* {score}%")
        lines.append(f"   HRV: {hrv/1000:.1f} ms | RHR: {rhr} bpm")
    else:
        lines.append("💚 *Recovery:* данные ещё не готовы")

    # Cycle
    if cycle:
        strain = cycle.get("score", {}).get("strain", "—")
        lines.append(f"🔥 *Strain:* {strain}")

    # Workouts
    if workouts:
        lines.append("\n🏋️ *Последние тренировки:*")
        for w in workouts[:3]:
            strain = w.get("score", {}).get("strain", 0)
            start = w.get("start")
            if start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m %H:%M")
            else:
                date_str = "—"
            lines.append(f"   • {date_str} — strain {strain:.1f}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# === Stage 2: Video Logging + Workout Matching ===

# Regex to parse YouTube URL + optional weight: "URL" or "URL 12kg"
_WEIGHT_PATTERN = re.compile(r"\b(\d{1,2})\s*(?:kg|кг)\b", re.IGNORECASE)


async def youtube_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle messages containing YouTube URLs."""
    if not update.effective_user or not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    telegram_id = update.effective_user.id
    message_time = update.message.date  # UTC-aware

    # Try to parse YouTube URL from message
    video_id = None
    for word in text.split():
        video_id = parse_youtube_url(word)
        if video_id:
            break

    if not video_id:
        return  # Not a YouTube URL, ignore

    # Parse optional weight: "12kg" or "20kg"
    kb_weight: int | None = None
    weight_match = _WEIGHT_PATTERN.search(text)
    if weight_match:
        parsed_weight = int(weight_match.group(1))
        if parsed_weight in (12, 20):
            kb_weight = parsed_weight

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)

            # Check if WHOOP is connected
            if not user.whoop_tokens_enc:
                await update.message.reply_text(
                    "⚠️ Сначала подключи WHOOP: /whoop"
                )
                return

            # Upsert Video (insert on conflict do nothing)
            existing_video = await session.get(Video, video_id)
            if not existing_video:
                session.add(Video(video_id=video_id))
                await session.flush()

            # Create PendingLog
            pending_log = PendingLog(
                user_id=user.id,
                video_id=video_id,
                kb_weight_kg=kb_weight,
                equipment_profile_at_time=user.equipment_profile,
                message_timestamp=message_time,
                state=PendingLogState.PENDING,
            )
            session.add(pending_log)
            await session.flush()
            log_id = str(pending_log.id)
            user_id = user.id
            equipment = user.equipment_profile
            tokens_enc = user.whoop_tokens_enc

    # If kettlebell video without weight and home mode, ask for weight
    if kb_weight is None and equipment == EquipmentProfile.HOME_FULL:
        # For MVP, always ask for weight if not specified (can refine later)
        # We'll proceed to matching, but ask for weight first if needed
        pass  # Continue to matching for now

    # Fetch workouts with auto-refresh on 401
    try:
        client, _ = await get_whoop_client_with_refresh(user_id, tokens_enc)
        workouts = await client.get_workouts(limit=25)
    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось получить тренировки: {e}"
        )
        return
    finally:
        if 'client' in locals():
            await client.close()

    candidates, status = match_workout(workouts, message_time)

    if status == "none":
        await update.message.reply_text(
            "🔍 Не нашёл подходящую тренировку в WHOOP.\n\n"
            "Проверь, что workout закончился и появился в WHOOP.",
            reply_markup=retry_keyboard(log_id),
        )
        return

    if status == "single":
        # Auto-match single candidate
        candidate = candidates[0]
        async with async_session_factory() as session:
            async with session.begin():
                pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                if pending_log:
                    pending_log.matched_workout_id = candidate.workout_id
                    pending_log.state = PendingLogState.MATCHED

        time_str = candidate.end.strftime("%H:%M")
        await update.message.reply_text(
            f"✅ Нашёл тренировку: {time_str} ({candidate.duration_min} мин)\n"
            f"Strain: {candidate.strain:.1f}\n\n"
            "Оцени нагрузку:",
            reply_markup=rpe_keyboard(log_id),
        )
        return

    # Multiple candidates — let user choose
    await update.message.reply_text(
        "🤔 Нашёл несколько тренировок. Выбери нужную:",
        reply_markup=workout_candidates_keyboard(candidates, log_id),
    )


async def workout_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle workout selection callback: workout_select:{workout_id}:{log_id}."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "workout_select":
        return

    workout_id = parts[1]
    log_id = parts[2]

    async with async_session_factory() as session:
        async with session.begin():
            pending_log = await session.get(PendingLog, uuid.UUID(log_id))
            if not pending_log:
                await query.edit_message_text("❌ Лог не найден")
                return

            pending_log.matched_workout_id = workout_id
            pending_log.state = PendingLogState.MATCHED

    await query.edit_message_text(
        "✅ Тренировка выбрана!\n\nОцени нагрузку:",
        reply_markup=rpe_keyboard(log_id),
    )


async def rpe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle RPE selection callback: rpe:{log_id}:{value}."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "rpe":
        return

    log_id = parts[1]
    rpe_value = int(parts[2])

    async with async_session_factory() as session:
        async with session.begin():
            pending_log = await session.get(PendingLog, uuid.UUID(log_id))
            if not pending_log:
                await query.edit_message_text("❌ Лог не найден")
                return

            # Create Feedback
            feedback = Feedback(
                user_id=pending_log.user_id,
                pending_log_id=pending_log.id,
                whoop_workout_id=pending_log.matched_workout_id,
                rpe_1_5=rpe_value,
            )
            session.add(feedback)

            # Mark log as confirmed
            pending_log.state = PendingLogState.CONFIRMED

    emoji = {1: "🟢", 2: "🟢", 3: "🟡", 4: "🟠", 5: "🔴"}.get(rpe_value, "")
    await query.edit_message_text(
        f"✅ Записано! RPE: {rpe_value} {emoji}\n\n"
        "Хорошей тренировки! 💪"
    )


async def kb_weight_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle kettlebell weight selection: kb_weight:{log_id}:{weight}."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "kb_weight":
        return

    log_id = parts[1]
    weight = int(parts[2])

    async with async_session_factory() as session:
        async with session.begin():
            pending_log = await session.get(PendingLog, uuid.UUID(log_id))
            if not pending_log:
                await query.edit_message_text("❌ Лог не найден")
                return

            pending_log.kb_weight_kg = weight

    await query.edit_message_text(f"✅ Вес: {weight} кг")


async def retry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle retry callback: retry:{log_id}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer("Ищу...")

    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != "retry":
        return

    log_id = parts[1]
    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            pending_log = await session.get(PendingLog, uuid.UUID(log_id))
            if not pending_log:
                await query.edit_message_text("❌ Лог не найден")
                return

            pending_log.retry_count += 1
            message_time = pending_log.message_timestamp

            # Get user tokens
            result = await session.execute(
                select(User).where(User.id == pending_log.user_id)
            )
            user = result.scalar_one_or_none()
            if not user or not user.whoop_tokens_enc:
                await query.edit_message_text("❌ WHOOP не подключен")
                return

            tokens_enc = user.whoop_tokens_enc

    # Fetch with larger limit and extended window
    tokens = decrypt_tokens(tokens_enc)
    client = WhoopClient(access_token=tokens.get("access_token"))
    try:
        workouts = await client.get_workouts(limit=25)
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")
        return
    finally:
        await client.close()

    candidates, status = match_workout(workouts, message_time, extended_window=True)

    if status == "none":
        await query.edit_message_text(
            "😕 Всё ещё не нашёл тренировку.\n\n"
            "Попробуй позже или проверь WHOOP."
        )
        return

    if status == "single":
        candidate = candidates[0]
        async with async_session_factory() as session:
            async with session.begin():
                pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                if pending_log:
                    pending_log.matched_workout_id = candidate.workout_id
                    pending_log.state = PendingLogState.MATCHED

        await query.edit_message_text(
            f"✅ Нашёл: {candidate.end.strftime('%H:%M')} ({candidate.duration_min} мин)\n\n"
            "Оцени нагрузку:",
            reply_markup=rpe_keyboard(log_id),
        )
        return

    await query.edit_message_text(
        "🤔 Нашёл несколько тренировок:",
        reply_markup=workout_candidates_keyboard(candidates, log_id),
    )


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /retry command — retry matching for last pending log."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                await update.message.reply_text("⚠️ Сначала напиши /start")
                return

            # Find last active pending log
            result = await session.execute(
                select(PendingLog)
                .where(
                    and_(
                        PendingLog.user_id == user.id,
                        PendingLog.state.in_([
                            PendingLogState.PENDING,
                            PendingLogState.MATCHED,
                        ]),
                    )
                )
                .order_by(PendingLog.created_at.desc())
                .limit(1)
            )
            pending_log = result.scalar_one_or_none()

            if not pending_log:
                await update.message.reply_text(
                    "🤷 Нет активных логов для повторного поиска"
                )
                return

            log_id = str(pending_log.id)
            message_time = pending_log.message_timestamp
            pending_log.retry_count += 1
            tokens_enc = user.whoop_tokens_enc

    if not tokens_enc:
        await update.message.reply_text("⚠️ Подключи WHOOP: /whoop")
        return

    tokens = decrypt_tokens(tokens_enc)
    client = WhoopClient(access_token=tokens.get("access_token"))
    try:
        workouts = await client.get_workouts(limit=25)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return
    finally:
        await client.close()

    candidates, status = match_workout(workouts, message_time, extended_window=True)

    if status == "none":
        await update.message.reply_text(
            "😕 Не нашёл тренировку. Попробуй позже.",
            reply_markup=retry_keyboard(log_id),
        )
        return

    if status == "single":
        candidate = candidates[0]
        async with async_session_factory() as session:
            async with session.begin():
                pl = await session.get(PendingLog, uuid.UUID(log_id))
                if pl:
                    pl.matched_workout_id = candidate.workout_id
                    pl.state = PendingLogState.MATCHED

        await update.message.reply_text(
            f"✅ Нашёл: {candidate.end.strftime('%H:%M')} ({candidate.duration_min} мин)\n\n"
            "Оцени нагрузку:",
            reply_markup=rpe_keyboard(log_id),
        )
        return

    await update.message.reply_text(
        "🤔 Нашёл несколько тренировок:",
        reply_markup=workout_candidates_keyboard(candidates, log_id),
    )


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /undo command — cancel last pending log.

    Note: Only deletes Feedback linked via pending_log_id to avoid
    removing manual feedback from other sources.
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                await update.message.reply_text("⚠️ Сначала напиши /start")
                return

            # Find last active pending log
            result = await session.execute(
                select(PendingLog)
                .where(
                    and_(
                        PendingLog.user_id == user.id,
                        PendingLog.state.in_([
                            PendingLogState.PENDING,
                            PendingLogState.MATCHED,
                        ]),
                    )
                )
                .order_by(PendingLog.created_at.desc())
                .limit(1)
            )
            pending_log = result.scalar_one_or_none()

            if not pending_log:
                await update.message.reply_text(
                    "🤷 Нет активных логов для отмены"
                )
                return

            # Delete linked feedback (only by pending_log_id)
            await session.execute(
                delete(Feedback).where(Feedback.pending_log_id == pending_log.id)
            )

            # Mark as cancelled
            pending_log.state = PendingLogState.CANCELLED

    await update.message.reply_text("✅ Отменено!")


# === Stage 3: Smart Questions ===

# Europe/Berlin timezone offset (simplified: use +1 for now)
BERLIN_OFFSET = timedelta(hours=1)


def _get_berlin_date() -> date:
    """Get current date in Europe/Berlin timezone."""
    now_utc = datetime.now(timezone.utc)
    berlin_time = now_utc + BERLIN_OFFSET
    return berlin_time.date()


def _is_morning_in_berlin() -> bool:
    """Check if current time is before 12:00 in Europe/Berlin."""
    now_utc = datetime.now(timezone.utc)
    berlin_time = now_utc + BERLIN_OFFSET
    return berlin_time.hour < 12


async def _needs_morning_prompt(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Check if user needs morning soreness/pain prompt today.
    
    Returns True if:
    - No morning feedback for today exists
    - AND (yesterday had planned workout OR yesterday had risky unattributed)
    """
    today = _get_berlin_date()
    
    # Check if already answered today
    result = await session.execute(
        select(Feedback).where(
            and_(
                Feedback.user_id == user_id,
                Feedback.feedback_date == today,
                Feedback.is_morning_prompt == True,
            )
        )
    )
    if result.scalar_one_or_none():
        return False  # Already answered
    
    # Check if yesterday had any logged workout
    yesterday = today - timedelta(days=1)
    result = await session.execute(
        select(PendingLog).where(
            and_(
                PendingLog.user_id == user_id,
                PendingLog.state == PendingLogState.CONFIRMED,
            )
        ).order_by(PendingLog.created_at.desc()).limit(1)
    )
    last_log = result.scalar_one_or_none()
    if last_log:
        log_date = last_log.created_at.date()
        if log_date == yesterday:
            return True
    
    # For MVP: always allow manual /morning trigger
    return True


async def morning_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/morning — trigger morning soreness/pain prompt."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    today = _get_berlin_date()
    date_str = today.isoformat()

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            
            # Check if already answered today
            result = await session.execute(
                select(Feedback).where(
                    and_(
                        Feedback.user_id == user.id,
                        Feedback.feedback_date == today,
                        Feedback.is_morning_prompt == True,
                    )
                )
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                await update.message.reply_text(
                    "✅ Ты уже ответил на утренний опрос сегодня!"
                )
                return

    await update.message.reply_text(
        "🌅 *Утренний опрос*\n\n"
        "Как ощущается мышечная усталость?",
        parse_mode="Markdown",
        reply_markup=soreness_keyboard(date_str),
    )


async def soreness_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle soreness selection: soreness:{date}:{value}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "soreness":
        return

    date_str = parts[1]
    soreness_value = int(parts[2])
    telegram_id = update.effective_user.id

    try:
        feedback_date = date.fromisoformat(date_str)
    except ValueError:
        await query.edit_message_text("❌ Неверная дата")
        return

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            
            # Create or update morning feedback
            result = await session.execute(
                select(Feedback).where(
                    and_(
                        Feedback.user_id == user.id,
                        Feedback.feedback_date == feedback_date,
                        Feedback.is_morning_prompt == True,
                    )
                )
            )
            feedback = result.scalar_one_or_none()
            
            if not feedback:
                feedback = Feedback(
                    user_id=user.id,
                    feedback_date=feedback_date,
                    is_morning_prompt=True,
                    soreness_0_3=soreness_value,
                )
                session.add(feedback)
            else:
                feedback.soreness_0_3 = soreness_value

    # If soreness == 0, skip pain prompt
    if soreness_value == 0:
        emoji = "🟢"
        await query.edit_message_text(
            f"✅ Записано! Soreness: {soreness_value} {emoji}\n\n"
            "Отличное восстановление! 💪"
        )
        return

    # Ask about pain locations
    emoji = {1: "🟡", 2: "🟠", 3: "🔴"}.get(soreness_value, "")
    
    # Store soreness in context for pain prompt
    context.user_data["pending_pain_date"] = date_str
    context.user_data["pending_pain_selected"] = set()
    
    await query.edit_message_text(
        f"Soreness: {soreness_value} {emoji}\n\n"
        "Где чувствуется дискомфорт?",
        reply_markup=pain_locations_keyboard(date_str),
    )


async def pain_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pain location toggle: pain:{date}:{location}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "pain":
        return

    date_str = parts[1]
    location = parts[2]

    # Get current selections from context
    selected = context.user_data.get("pending_pain_selected", set())
    
    if location == "нет":
        # "нет" clears all other selections
        selected = {"нет"}
    else:
        # Toggle this location
        selected.discard("нет")  # Remove "нет" if selecting something else
        if location in selected:
            selected.remove(location)
        else:
            selected.add(location)
    
    context.user_data["pending_pain_selected"] = selected
    
    await query.edit_message_text(
        "Где чувствуется дискомфорт?\n\n"
        f"Выбрано: {', '.join(selected) if selected else 'ничего'}",
        reply_markup=pain_locations_keyboard(date_str, selected),
    )


async def pain_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pain done: pain_done:{date}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != "pain_done":
        return

    date_str = parts[1]
    telegram_id = update.effective_user.id
    selected = context.user_data.get("pending_pain_selected", set())

    try:
        feedback_date = date.fromisoformat(date_str)
    except ValueError:
        await query.edit_message_text("❌ Неверная дата")
        return

    # Convert "нет" to empty list
    pain_list = [] if "нет" in selected else list(selected)

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            
            result = await session.execute(
                select(Feedback).where(
                    and_(
                        Feedback.user_id == user.id,
                        Feedback.feedback_date == feedback_date,
                        Feedback.is_morning_prompt == True,
                    )
                )
            )
            feedback = result.scalar_one_or_none()
            
            if feedback:
                feedback.pain_locations = pain_list

    # Clear context
    context.user_data.pop("pending_pain_date", None)
    context.user_data.pop("pending_pain_selected", None)

    if pain_list:
        await query.edit_message_text(
            f"✅ Записано!\n\n"
            f"Дискомфорт: {', '.join(pain_list)}\n\n"
            "Учту это в рекомендациях!"
        )
    else:
        await query.edit_message_text(
            "✅ Записано! Никаких проблем.\n\n"
            "Хорошего дня! 💪"
        )


async def unattributed_rpe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle RPE for unattributed workout: unattr_rpe:{workout_id}:{value}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "unattr_rpe":
        return

    workout_id = parts[1]
    rpe_value = int(parts[2])
    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            
            # Create Feedback for unattributed workout
            feedback = Feedback(
                user_id=user.id,
                whoop_workout_id=workout_id,
                rpe_1_5=rpe_value,
            )
            session.add(feedback)

    emoji = {1: "🟢", 2: "🟢", 3: "🟡", 4: "🟠", 5: "🔴"}.get(rpe_value, "")
    await query.edit_message_text(
        f"✅ Записано! RPE: {rpe_value} {emoji}\n\n"
        "Спасибо за фидбек!"
    )
