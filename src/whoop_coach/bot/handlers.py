"""Telegram bot command and callback handlers."""

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from whoop_coach.bot.keyboards import (
    EQUIPMENT_LABELS,
    PAIN_LOCATIONS,
    equipment_keyboard,
    gear_with_swing_keyboard,
    kb_used_done_keyboard,
    kb_used_keyboard,
    kb_weight_keyboard,
    movement_tags_keyboard,
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
from whoop_coach.matching import MatchCandidate, match_workout
from whoop_coach.whoop.client import WhoopClient
from whoop_coach.youtube import parse_youtube_url
from whoop_coach.videos.service import (
    upsert_video,
    get_last_used_video,
    get_last_video_log,
    get_video_strain_aggregates_by_profile,
    get_video_effort_aggregates_by_profile,
    get_video_overall_aggregates,
    profile_key,
    format_session_metrics,
    rpe_mean_to_words,
    escape_html,
)

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
        print(f"[TOKEN] Initial request failed with status {e.response.status_code}")
        if e.response.status_code != 401:
            raise

    # Token expired — refresh
    print("[TOKEN] Access token expired, attempting refresh...")
    await client.close()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("[TOKEN] No refresh token available!")
        raise ValueError("No refresh token available")

    client = WhoopClient()
    try:
        new_tokens = await client.refresh_tokens(refresh_token)
        print("[TOKEN] Refresh successful, saving new tokens...")
    except httpx.HTTPStatusError as e:
        print(f"[TOKEN] Refresh failed with status {e.response.status_code}: {e.response.text}")
        await client.close()
        raise ValueError(f"Token refresh failed: {e.response.status_code}")
    
    client.access_token = new_tokens.access_token

    # Save new tokens to DB
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if user:
                user.whoop_tokens_enc = encrypt_tokens(new_tokens.to_dict())
                print(f"[TOKEN] New tokens saved for user {user_id}")

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
        "*Основные:*\n"
        "/start — начать\n"
        "/whoop — подключить WHOOP\n"
        "/disconnect — отключить WHOOP\n"
        "/last — последние данные WHOOP\n"
        "/help — эта справка\n\n"
        "*Тренировки:*\n"
        "/gear — выбрать инвентарь\n"
        "/profile — установить веса (H/S)\n"
        "/plan — план на сегодня\n"
        "/morning — утренний опрос\n"
        "/retry — повторить матчинг\n\n"
        "*Видео:*\n"
        "/video\\_last — инфо о последнем видео\n"
        "/video\\_tag *ID* — разметить теги\n\n"
        "*Логирование:*\n"
        "Отправь YouTube URL (с опц. весом):\n"
        "`https://youtube.com/... 20kg`",
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


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/profile [heavy] [swing] — показать или установить веса KB."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    args = context.args or []

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            
            if len(args) == 0:
                # Show current profile
                await update.message.reply_text(
                    f"🏋️ *Текущий профиль:*\n\n"
                    f"База (heavy): {user.kb_heavy_kg} кг\n"
                    f"Свинг (swing): {user.kb_swing_kg} кг\n"
                    f"Overhead max: {user.kb_overhead_max_kg} кг\n\n"
                    f"Чтобы изменить: `/profile 20 12`\n"
                    f"(первое — база, второе — свинг)",
                    parse_mode="Markdown",
                )
                return
            
            if len(args) == 2:
                try:
                    heavy = int(args[0])
                    swing = int(args[1])
                    user.kb_heavy_kg = heavy
                    user.kb_swing_kg = swing
                    await update.message.reply_text(
                        f"✅ Профиль обновлён:\n"
                        f"База: {heavy} кг\n"
                        f"Свинг: {swing} кг",
                    )
                    return
                except ValueError:
                    pass
            
            await update.message.reply_text(
                "❌ Формат: `/profile 20 12`\n(база, свинг в кг)",
                parse_mode="Markdown",
            )


async def gear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gear command — show current equipment and selection buttons."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            current_profile = user.equipment_profile
            current_swing = user.kb_swing_kg

    label = EQUIPMENT_LABELS[current_profile]
    await update.message.reply_text(
        f"🎒 *Сейчас:* {label}\n🏋️ *Свинг:* {current_swing} кг\n\nВыбери:",
        parse_mode="Markdown",
        reply_markup=gear_with_swing_keyboard(current_profile, current_swing),
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
            current_swing = user.kb_swing_kg

    label = EQUIPMENT_LABELS[new_profile]
    await query.edit_message_text(
        f"🎒 *Сейчас:* {label}\n🏋️ *Свинг:* {current_swing} кг\n\nВыбери:",
        parse_mode="Markdown",
        reply_markup=gear_with_swing_keyboard(new_profile, current_swing),
    )


async def kb_swing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle swing weight toggle: kb_swing:{weight}."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    # Parse callback data: "kb_swing:12" or "kb_swing:20"
    _, weight_str = query.data.split(":", 1)
    try:
        new_weight = int(weight_str)
    except ValueError:
        return
    
    if new_weight not in (12, 20):
        return

    await query.answer(f"Свинг: {new_weight} кг")

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            user.kb_swing_kg = new_weight
            current_profile = user.equipment_profile

    label = EQUIPMENT_LABELS[current_profile]
    await query.edit_message_text(
        f"🎒 *Сейчас:* {label}\n🏋️ *Свинг:* {new_weight} кг\n\nВыбери:",
        parse_mode="Markdown",
        reply_markup=gear_with_swing_keyboard(current_profile, new_weight),
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
            user_id = user.id

    if not tokens_enc:
        await update.message.reply_text(
            "⚠️ *WHOOP не подключен*\n\n"
            "Используй /whoop для подключения.",
            parse_mode="Markdown",
        )
        return

    # Fetch data from WHOOP with auto token refresh
    try:
        client, tokens_refreshed = await get_whoop_client_with_refresh(user_id, tokens_enc)
        
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

    except ValueError as e:
        # Token refresh failed — need to re-auth
        await update.message.reply_text(
            f"⚠️ Токен истёк и не удалось обновить.\n\n"
            "Используй /disconnect затем /whoop для переподключения.",
        )
        return
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при получении данных: {e}\n\n"
            "Попробуй переподключить /whoop",
        )
        return
    finally:
        if 'client' in locals():
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


def _persist_whoop_snapshot(
    pending_log: PendingLog,
    candidate: MatchCandidate,
) -> None:
    """Persist WHOOP workout snapshot into PendingLog."""
    pending_log.whoop_workout_id = candidate.workout_id
    pending_log.whoop_workout_type = candidate.workout_type
    pending_log.whoop_duration_s = candidate.duration_min * 60
    pending_log.whoop_strain = candidate.strain if candidate.strain else None
    pending_log.whoop_hr_avg = candidate.hr_avg
    pending_log.whoop_hr_max = candidate.hr_max
    pending_log.matched_at = datetime.now(timezone.utc)


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

    logger.info(f"YouTube URL detected: video_id={video_id}, user={telegram_id}")

    try:
        await _process_youtube_url(update, context, video_id, text, telegram_id, message_time)
    except Exception as e:
        logger.exception(f"Error processing YouTube URL: {e}")
        # Show full error for debugging
        error_msg = str(e)[:200] if str(e) else type(e).__name__
        await update.message.reply_text(
            f"❌ Ошибка: {error_msg}"
        )


async def _process_youtube_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    video_id: str,
    text: str,
    telegram_id: int,
    message_time,
) -> None:
    """Internal: process YouTube URL after parsing."""

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

            # Upsert Video with usage tracking
            video = await upsert_video(session, video_id)
            await session.flush()  # Ensure Video exists before FK reference

            # Capture KB caps for prompt
            now = datetime.now(timezone.utc)
            should_prompt_kb = (
                user.equipment_profile == EquipmentProfile.HOME_FULL
                and kb_weight is None
            )

            # Create PendingLog with KB cap snapshots
            pending_log = PendingLog(
                user_id=user.id,
                video_id=video_id,
                kb_weight_kg=kb_weight,
                equipment_profile_at_time=user.equipment_profile,
                message_timestamp=message_time,
                state=PendingLogState.PENDING,
                # KB capability snapshots (copied from user defaults)
                kb_overhead_max_kg_at_time=user.kb_overhead_max_kg,
                kb_heavy_kg_at_time=user.kb_heavy_kg,
                kb_swing_kg_at_time=user.kb_swing_kg,
                # Set prompt timestamp if we will ask
                kb_used_prompt_sent_at=now if should_prompt_kb else None,
            )
            session.add(pending_log)
            await session.flush()
            log_id = str(pending_log.id)
            user_id = user.id
            equipment = user.equipment_profile
            tokens_enc = user.whoop_tokens_enc
            heavy_kg = user.kb_heavy_kg
            swing_kg = user.kb_swing_kg

    # Send kb_used prompt AFTER commit (ensures idempotency if send fails)
    if kb_weight is None and equipment == EquipmentProfile.HOME_FULL:
        await update.message.reply_text(
            "Записал. Какие веса использовал в этот раз?",
            reply_markup=kb_used_keyboard(log_id, heavy_kg, swing_kg),
        )

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
                    _persist_whoop_snapshot(pending_log, candidate)

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

            # Get user tokens for WHOOP fetch
            result = await session.execute(
                select(User).where(User.id == pending_log.user_id)
            )
            user = result.scalar_one_or_none()
            if not user or not user.whoop_tokens_enc:
                # Still set match, just skip snapshot
                pending_log.matched_workout_id = workout_id
                pending_log.state = PendingLogState.MATCHED
                pending_log.matched_at = datetime.now(timezone.utc)
            else:
                # Fetch workout to get full data for snapshot
                tokens_enc = user.whoop_tokens_enc
                user_id = user.id

    # Fetch workout data for snapshot (outside transaction)
    if user and user.whoop_tokens_enc:
        try:
            client, _ = await get_whoop_client_with_refresh(user_id, tokens_enc)
            workouts = await client.get_workouts(limit=25)
            await client.close()

            # Find matching workout
            candidate = None
            for w in workouts:
                c = MatchCandidate.from_whoop_workout(w)
                if c.workout_id == workout_id:
                    candidate = c
                    break

            async with async_session_factory() as session:
                async with session.begin():
                    pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                    if pending_log:
                        pending_log.matched_workout_id = workout_id
                        pending_log.state = PendingLogState.MATCHED
                        if candidate:
                            _persist_whoop_snapshot(pending_log, candidate)
                        else:
                            pending_log.matched_at = datetime.now(timezone.utc)
        except Exception:
            # On error, still mark as matched but skip snapshot
            async with async_session_factory() as session:
                async with session.begin():
                    pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                    if pending_log:
                        pending_log.matched_workout_id = workout_id
                        pending_log.state = PendingLogState.MATCHED
                        pending_log.matched_at = datetime.now(timezone.utc)

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


# === Stage 5: KB Used Callbacks ===

# Two explicit patterns for cleaner validation (per user feedback)
import re
_KB_USED_WEIGHT_PATTERN = re.compile(r"^kb_used:([0-9a-f-]+):(heavy|swing):(12|20)$")
_KB_USED_ACTION_PATTERN = re.compile(r"^kb_used:([0-9a-f-]+):(keep|skip|done)$")


async def kb_used_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle KB used session weights: kb_used:{log_id}:{action}:{value?}.
    
    Patterns:
        kb_used:{log_id}:heavy:12|20
        kb_used:{log_id}:swing:12|20
        kb_used:{log_id}:keep
        kb_used:{log_id}:skip
        kb_used:{log_id}:done
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    
    # Match weight pattern: heavy/swing with 12|20
    weight_match = _KB_USED_WEIGHT_PATTERN.match(data)
    if weight_match:
        log_id = weight_match.group(1)
        weight_type = weight_match.group(2)  # "heavy" or "swing"
        weight_value = int(weight_match.group(3))
        
        await query.answer(f"{'База' if weight_type == 'heavy' else 'Свинг'}: {weight_value} кг")
        
        async with async_session_factory() as session:
            async with session.begin():
                pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                if not pending_log:
                    await query.edit_message_text("❌ Лог не найден")
                    return
                
                # Check if already answered
                if pending_log.kb_used_answered_at:
                    await query.answer("Уже сохранено", show_alert=False)
                    return
                
                # Update the appropriate weight
                if weight_type == "heavy":
                    pending_log.kb_heavy_kg_at_time = weight_value
                else:
                    pending_log.kb_swing_kg_at_time = weight_value
                
                # Get current values for UI
                heavy_kg = pending_log.kb_heavy_kg_at_time or 20
                swing_kg = pending_log.kb_swing_kg_at_time or 12
        
        # Edit message with current selection + Готово button
        await query.edit_message_text(
            f"Принято: база {heavy_kg} кг, свинг {swing_kg} кг.",
            reply_markup=kb_used_done_keyboard(log_id, heavy_kg, swing_kg),
        )
        return
    
    # Match action pattern: keep/skip/done
    action_match = _KB_USED_ACTION_PATTERN.match(data)
    if action_match:
        log_id = action_match.group(1)
        action = action_match.group(2)
        
        async with async_session_factory() as session:
            async with session.begin():
                pending_log = await session.get(PendingLog, uuid.UUID(log_id))
                if not pending_log:
                    await query.answer("Лог не найден", show_alert=True)
                    return
                
                # Check if already answered
                if pending_log.kb_used_answered_at:
                    await query.answer("Уже сохранено", show_alert=False)
                    return
                
                now = datetime.now(timezone.utc)
                
                if action == "keep":
                    # Reset to user defaults
                    user = await session.get(User, pending_log.user_id)
                    if user:
                        pending_log.kb_heavy_kg_at_time = user.kb_heavy_kg
                        pending_log.kb_swing_kg_at_time = user.kb_swing_kg
                    pending_log.kb_used_answered_at = now
                    await query.answer("Как в /gear")
                    await query.edit_message_text(
                        "✅ Оставили веса из /gear."
                    )
                
                elif action == "skip":
                    # Just finalize without changes
                    pending_log.kb_used_answered_at = now
                    await query.answer("Пропущено")
                    await query.edit_message_text(
                        "⏭️ Пропустили выбор весов."
                    )
                
                elif action == "done":
                    # Finalize current selection
                    pending_log.kb_used_answered_at = now
                    heavy_kg = pending_log.kb_heavy_kg_at_time or 20
                    swing_kg = pending_log.kb_swing_kg_at_time or 12
                    await query.answer("Сохранено!")
                    await query.edit_message_text(
                        f"✅ Сохранено: база {heavy_kg} кг, свинг {swing_kg} кг."
                    )
        return
    
    # Unknown pattern
    await query.answer("Неизвестная команда", show_alert=True)




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
                    _persist_whoop_snapshot(pending_log, candidate)

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
                    _persist_whoop_snapshot(pl, candidate)

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


# === Stage 5: Video Tagging Commands & Callbacks ===

async def tag_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tag_last — open tagging UI for most recently used video."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    async with async_session_factory() as session:
        async with session.begin():
            user = await get_or_create_user(session, telegram_id)
            video = await get_last_used_video(session, user.id)
            
            if not video:
                await update.message.reply_text(
                    "🤷 Нет залогированных видео для разметки."
                )
                return
            
            video_id = video.video_id
            current_tags = set(video.movement_tags) if video.movement_tags else set()

    await update.message.reply_text(
        f"🏷️ Разметить видео `{video_id}`:\n\n"
        "Выбери паттерны движений:",
        parse_mode="Markdown",
        reply_markup=movement_tags_keyboard(video_id, current_tags),
    )


async def video_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/video_last — show last video info + session metrics + profile aggregates."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await get_or_create_user(session, telegram_id)
                
                result = await get_last_video_log(session, user.id)
                if not result:
                    await update.message.reply_text("🤷 Нет залогированных видео.")
                    return
                
                video, last_log = result
                video_id = video.video_id
                tags = video.movement_tags if video.movement_tags else []
                usage_count = video.usage_count
                last_used = video.last_used_at
                title = video.title or "—"
                
                # Get profile weights
                heavy_kg = last_log.kb_heavy_kg_at_time or user.kb_heavy_kg
                swing_kg = last_log.kb_swing_kg_at_time or user.kb_swing_kg
                current_profile = profile_key(heavy_kg, swing_kg)
                
                # Session metrics
                session_line = format_session_metrics(last_log)
                weights_line = f"Веса (факт): база {heavy_kg} · свинг {swing_kg}  (профиль {current_profile})"
                
                # Aggregates
                strain_aggs = await get_video_strain_aggregates_by_profile(session, user.id, video_id)
                effort_aggs = await get_video_effort_aggregates_by_profile(session, user.id, video_id)
                overall = await get_video_overall_aggregates(session, user.id, video_id)

        tags_str = ", ".join(tags) if tags else "не размечено"
        last_used_str = last_used.strftime("%d.%m %H:%M") if last_used else "—"
        
        # Escape for HTML
        title_safe = escape_html(title)
        tags_safe = escape_html(tags_str)
        
        lines = [
            f"📼 <b>Последнее видео</b>\n",
            f"ID: <code>{video_id}</code>",
            f"Название: {title_safe}",
            f"🔖 Теги: {tags_safe}",
            f"📊 Использований: {usage_count}",
            f"🕐 Последнее: {last_used_str}",
            f'<a href="https://www.youtube.com/watch?v={video_id}">Открыть на YouTube</a>\n',
            session_line,
            weights_line,
        ]
        
        # Current profile aggregates
        strain_by_profile = {(a.heavy_kg, a.swing_kg): a for a in strain_aggs}
        effort_by_profile = {(a.heavy_kg, a.swing_kg): a for a in effort_aggs}
        
        current_strain = strain_by_profile.get((heavy_kg, swing_kg))
        current_effort = effort_by_profile.get((heavy_kg, swing_kg))
        
        # Always show current profile section
        lines.append(f"\n📊 <b>По профилю {current_profile}</b>")
        if current_strain or current_effort:
            if current_strain:
                lines.append(f"strain: {current_strain.avg_value:.1f} (n={current_strain.count})")
            if current_effort:
                word = rpe_mean_to_words(current_effort.avg_value)
                lines.append(f'effort: {current_effort.avg_value:.1f} — ближе к "{word}" (n={current_effort.count})')
        else:
            lines.append("нет данных")
        
        # Overall aggregates
        if overall.strain_count > 0 or overall.rpe_count > 0:
            lines.append(f"\n📈 <b>Общее по видео</b>")
            if overall.avg_strain is not None and overall.strain_count > 0:
                lines.append(f"strain: {overall.avg_strain:.1f} (n={overall.strain_count})")
            if overall.avg_rpe is not None and overall.rpe_count > 0:
                word = rpe_mean_to_words(overall.avg_rpe)
                lines.append(f'effort: {overall.avg_rpe:.1f} — ближе к "{word}" (n={overall.rpe_count})')
        
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"video_last_command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


# Tag toggle pattern: tag:{video_id}:{tag}
_TAG_TOGGLE_PATTERN = re.compile(r"^tag:([a-zA-Z0-9_-]+):([a-z]+)$")


async def tag_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle tag toggle: tag:{video_id}:{tag}."""
    query = update.callback_query
    if not query or not query.data:
        return

    match = _TAG_TOGGLE_PATTERN.match(query.data)
    if not match:
        return

    video_id = match.group(1)
    tag = match.group(2)

    await query.answer(tag)

    async with async_session_factory() as session:
        async with session.begin():
            video = await session.get(Video, video_id)
            if not video:
                await query.edit_message_text("❌ Видео не найдено")
                return
            
            # Toggle tag in list
            current_tags = set(video.movement_tags) if video.movement_tags else set()
            if tag in current_tags:
                current_tags.remove(tag)
            else:
                current_tags.add(tag)
            
            video.movement_tags = list(current_tags)

    # Edit message with updated keyboard
    tags_str = ", ".join(sorted(current_tags)) if current_tags else "—"
    await query.edit_message_text(
        f"🏷️ Разметить видео `{video_id}`:\n\n"
        f"Текущие теги: {tags_str}",
        parse_mode="Markdown",
        reply_markup=movement_tags_keyboard(video_id, current_tags),
    )


async def tag_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle tag done: tag_done:{video_id}."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != "tag_done":
        return

    video_id = parts[1]

    async with async_session_factory() as session:
        async with session.begin():
            video = await session.get(Video, video_id)
            if not video:
                await query.answer("Видео не найдено", show_alert=True)
                return
            
            tags = video.movement_tags if video.movement_tags else []

    tags_str = ", ".join(tags) if tags else "не размечено"
    await query.answer("Сохранено!")
    await query.edit_message_text(
        f"✅ Разметка сохранена!\n\n"
        f"Теги: {tags_str}"
    )


async def tag_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle tag skip: tag_skip:{video_id}."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != "tag_skip":
        return

    await query.answer("Пропущено")
    await query.edit_message_text("⏭️ Разметка пропущена.")

