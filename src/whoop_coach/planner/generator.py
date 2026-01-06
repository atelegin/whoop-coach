"""3-day plan generator.

Combines constraints and scoring to generate personalized plans.
v0.5: Added soft scoring context with fatigue/history signals.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from whoop_coach.db.models import (
    DailyPlan,
    EquipmentProfile,
    Feedback,
    User,
)
from whoop_coach.planner.options import (
    ALL_OPTIONS,
    WorkoutOption,
    get_option_by_id,
    get_modality,
)
from whoop_coach.planner.constraints import filter_options, ensure_z3_included
from whoop_coach.planner.scoring import (
    score_options,
    score_options_v2,
    select_top_options,
    select_diversified_options,
    ScoredOption,
    ScoringContext,
)


logger = logging.getLogger(__name__)

# Pain locations that indicate leg issues
LEG_PAIN_LOCATIONS = {"колено", "икры", "бедро", "лодыжка", "бёдра"}


@dataclass
class ThreeDayPlan:
    """Generated 3-day training plan."""
    
    today_options: list[ScoredOption]
    tomorrow_draft: list[ScoredOption]
    day_after_draft: list[ScoredOption]
    recovery_score: int
    sleep_summary: str
    equipment_profile: EquipmentProfile
    plan_date: date
    scoring_debug: dict | None = None
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        result = {
            "today_options": [o.to_dict() for o in self.today_options],
            "tomorrow_draft": [o.to_dict() for o in self.tomorrow_draft],
            "day_after_draft": [o.to_dict() for o in self.day_after_draft],
            "recovery_score": self.recovery_score,
            "sleep_summary": self.sleep_summary,
            "equipment_profile": self.equipment_profile.value,
            "plan_date": self.plan_date.isoformat(),
        }
        if self.scoring_debug:
            result["scoring_debug"] = self.scoring_debug
        return result


async def get_z4_stats(
    session: AsyncSession,
    user_id: uuid.UUID,
    today: date,
) -> tuple[int, float | None]:
    """Get Z4 stats for the last 7 days.
    
    Returns:
        Tuple of (z4_count, hours_since_last_z4)
    """
    # For MVP: return defaults (0, None)
    # TODO: Track Z4 from Feedback/PendingLog
    return 0, None


async def get_yesterday_strain(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> float | None:
    """Get yesterday's strain from workout history.
    
    For MVP: returns None (use default scoring)
    """
    return None


async def get_morning_feedback(
    session: AsyncSession,
    user_id: uuid.UUID,
    feedback_date: date,
) -> tuple[int | None, list[str] | None]:
    """Get today's morning feedback (soreness, pain_locations).
    
    Returns:
        Tuple of (soreness_0_3, pain_locations)
    """
    result = await session.execute(
        select(Feedback).where(
            and_(
                Feedback.user_id == user_id,
                Feedback.feedback_date == feedback_date,
                Feedback.is_morning_prompt == True,
            )
        )
    )
    feedback = result.scalar_one_or_none()
    
    if feedback:
        return feedback.soreness_0_3, feedback.pain_locations
    return None, None


async def get_recent_heavy_count(
    session: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    days: int = 3,
) -> int:
    """Count workouts with RPE >= 4 in the last N days.
    
    Returns:
        Count of heavy workouts (rpe_1_5 >= 4)
    """
    start_date = today - timedelta(days=days)
    
    result = await session.execute(
        select(Feedback).where(
            and_(
                Feedback.user_id == user_id,
                Feedback.rpe_1_5 >= 4,
                Feedback.is_morning_prompt == False,
                Feedback.created_at >= datetime.combine(start_date, datetime.min.time()),
            )
        )
    )
    feedbacks = result.scalars().all()
    return len(feedbacks)


async def get_last_modalities(
    session: AsyncSession,
    user_id: uuid.UUID,
    today: date,
) -> tuple[str | None, tuple[str, str] | None]:
    """Get last modality and last two modalities from recent workouts.
    
    Priority:
    1. Last DailyPlan with selected_option_id
    2. Last Feedback with whoop_workout_id (fallback)
    
    Returns:
        Tuple of (last_modality, last_two_modalities)
    """
    # Try DailyPlan first
    result = await session.execute(
        select(DailyPlan).where(
            and_(
                DailyPlan.user_id == user_id,
                DailyPlan.plan_date < today,
                DailyPlan.selected_option_id.isnot(None),
            )
        ).order_by(desc(DailyPlan.plan_date)).limit(2)
    )
    plans = result.scalars().all()
    
    modalities: list[str] = []
    for plan in plans:
        opt = get_option_by_id(plan.selected_option_id)
        if opt:
            modalities.append(get_modality(opt))
    
    # If not enough from DailyPlan, we could look at Feedback
    # but for MVP, use what we have
    
    last_modality = modalities[0] if modalities else None
    last_two = (
        (modalities[1], modalities[0])  # (day-2, day-1)
        if len(modalities) >= 2
        else None
    )
    
    return last_modality, last_two


async def compute_leg_doms_high(
    session: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    today_soreness: int | None,
    today_pain: list[str] | None,
) -> bool:
    """Compute last_leg_doms_high boolean.
    
    Formula:
    - yesterday_soreness == 3 OR
    - pain contains leg locations OR
    - last workout is leg-heavy AND rpe >= 4
    """
    # Check today's morning soreness/pain (which reflects yesterday's impact)
    if today_soreness is not None and today_soreness >= 3:
        return True
    
    if today_pain:
        pain_set = set(p.lower() for p in today_pain)
        if pain_set & LEG_PAIN_LOCATIONS:
            return True
    
    # Check last workout
    yesterday = today - timedelta(days=1)
    result = await session.execute(
        select(Feedback).where(
            and_(
                Feedback.user_id == user_id,
                Feedback.is_morning_prompt == False,
                Feedback.rpe_1_5.isnot(None),
            )
        ).order_by(desc(Feedback.created_at)).limit(1)
    )
    last_feedback = result.scalar_one_or_none()
    
    if last_feedback and last_feedback.rpe_1_5 and last_feedback.rpe_1_5 >= 4:
        # Check if it was leg-heavy via the selected plan option
        # For MVP: assume leg-heavy if high RPE and recent
        feedback_date = last_feedback.created_at.date()
        if feedback_date >= yesterday:
            # Could be leg-heavy, treat high RPE recent workout as potential leg load
            return True
    
    return False


async def compute_scoring_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_date: date,
    recovery_score: int,
    soreness: int | None,
    pain_locations: list[str] | None,
) -> ScoringContext:
    """Build soft scoring context from recent history.
    
    Computes:
    - recent_heavy_count_3d: workouts with RPE >= 4 in last 3 days
    - last_modality: modality of most recent workout
    - last_two_modalities: (day-2, day-1) modalities
    - last_leg_doms_high: boolean formula
    """
    # Count recent heavy workouts
    recent_heavy = await get_recent_heavy_count(session, user_id, plan_date, days=3)
    
    # Get last modalities
    last_mod, last_two = await get_last_modalities(session, user_id, plan_date)
    
    # Compute leg DOMS
    leg_doms = await compute_leg_doms_high(
        session, user_id, plan_date, soreness, pain_locations
    )
    
    ctx = ScoringContext(
        recovery_score=recovery_score,
        soreness=soreness or 0,
        recent_heavy_count_3d=recent_heavy,
        last_leg_doms_high=leg_doms,
        last_modality=last_mod,
        last_two_modalities=last_two,
    )
    
    logger.info(
        f"Scoring context: recovery={recovery_score}, heavy_3d={recent_heavy}, "
        f"leg_doms={leg_doms}, last_mod={last_mod}"
    )
    
    return ctx


async def generate_3day_plan(
    user_id: uuid.UUID,
    recovery: dict[str, Any],
    sleep: dict[str, Any],
    session: AsyncSession,
) -> ThreeDayPlan:
    """Generate a 3-day training plan based on recovery and user state.
    
    Args:
        user_id: User's UUID
        recovery: WHOOP recovery data
        sleep: WHOOP sleep data
        session: Database session
        
    Returns:
        ThreeDayPlan with scored options for today, tomorrow, day_after
    """
    # Get user
    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    equipment_profile = user.equipment_profile
    
    # Extract recovery score
    score_data = recovery.get("score", {})
    recovery_score = score_data.get("recovery_score", 50)
    
    # Extract sleep info
    sleep_duration = sleep.get("score", {}).get("stage_summary", {})
    sleep_hours = (
        sleep_duration.get("total_in_bed_time_milli", 0) / 3600000
    )
    sleep_summary = f"{sleep_hours:.1f}ч сна"
    
    # Get today's date
    today = date.today()
    
    # Get morning feedback
    soreness, pain_locations = await get_morning_feedback(session, user_id, today)
    
    # Get Z4 stats
    z4_count, hours_since_z4 = await get_z4_stats(session, user_id, today)
    
    # Build soft scoring context
    scoring_ctx = await compute_scoring_context(
        session, user_id, today, recovery_score, soreness, pain_locations
    )
    
    # === Generate Today's Options ===
    filtered = filter_options(
        all_options=ALL_OPTIONS,
        equipment_profile=equipment_profile,
        pain_locations=pain_locations,
        soreness=soreness,
        z4_last_7_days=z4_count,
        hours_since_last_z4=hours_since_z4,
        had_heavy_leg_yesterday=scoring_ctx.last_leg_doms_high,
        recovery_score=recovery_score,
    )
    
    # Ensure Z3 is included if any run is allowed
    filtered = ensure_z3_included(filtered, ALL_OPTIONS)
    
    # Score with v2 (soft scoring context)
    scored = score_options_v2(filtered, scoring_ctx)
    
    # Select diversified options
    today_options = select_diversified_options(scored)
    
    # === Tomorrow/Day After: Simple drafts ===
    # For MVP: use same scored list with different selection
    tomorrow_draft = select_top_options(scored, count=2, ensure_variety=True)
    day_after_draft = select_top_options(scored, count=2, ensure_variety=True)
    
    # Build compact scoring debug
    scoring_debug = {
        "ctx": {
            "rec": recovery_score,
            "heavy_3d": scoring_ctx.recent_heavy_count_3d,
            "leg_doms": scoring_ctx.last_leg_doms_high,
            "last_mod": scoring_ctx.last_modality,
        },
        "options": [
            {
                "id": s.option.id,
                "debug": s.debug.to_dict() if s.debug else None,
            }
            for s in scored[:5]  # Top 5 for debug
        ],
    }
    
    plan = ThreeDayPlan(
        today_options=today_options,
        tomorrow_draft=tomorrow_draft,
        day_after_draft=day_after_draft,
        recovery_score=recovery_score,
        sleep_summary=sleep_summary,
        equipment_profile=equipment_profile,
        plan_date=today,
        scoring_debug=scoring_debug,
    )
    
    # Store plan in DB
    daily_plan = DailyPlan(
        user_id=user_id,
        plan_date=today,
        sleep_id=sleep.get("id"),
        cycle_id=sleep.get("cycle_id"),
        recovery_score=recovery_score,
        timezone_offset=sleep.get("timezone_offset"),
        options_shown=plan.to_dict(),
        scoring_debug=scoring_debug,
        sent_at=datetime.utcnow(),
    )
    session.add(daily_plan)
    await session.commit()
    
    return plan


def format_plan_message(plan: ThreeDayPlan) -> str:
    """Format 3-day plan as Telegram message."""
    lines = [
        f"☀️ Доброе утро! Recovery: {plan.recovery_score}% ({plan.sleep_summary})",
        "",
        f"🏠 Инвентарь: {_equipment_label(plan.equipment_profile)}",
        "",
        "📋 *Сегодня (выбери 1):*",
    ]
    
    for i, opt in enumerate(plan.today_options):
        letter = chr(ord("A") + i)
        lines.append(f"  {letter}. {opt.option.name_ru}")
    
    lines.extend([
        "",
        "📅 *Завтра/послезавтра (черновик):*",
    ])
    
    tomorrow_names = [o.option.name_ru for o in plan.tomorrow_draft[:2]]
    lines.append(f"  {' / '.join(tomorrow_names)}")
    
    return "\n".join(lines)


def _equipment_label(profile: EquipmentProfile) -> str:
    """Get human-readable equipment label."""
    labels = {
        EquipmentProfile.HOME_FULL: "дом (гиря)",
        EquipmentProfile.TRAVEL_BANDS: "поездка (ремни)",
        EquipmentProfile.TRAVEL_NONE: "поездка (ничего)",
    }
    return labels.get(profile, "дом")
