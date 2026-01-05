"""3-day plan generator.

Combines constraints and scoring to generate personalized plans.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from whoop_coach.db.models import (
    DailyPlan,
    EquipmentProfile,
    Feedback,
    User,
)
from whoop_coach.planner.options import ALL_OPTIONS, WorkoutOption
from whoop_coach.planner.constraints import filter_options, ensure_z3_included
from whoop_coach.planner.scoring import score_options, select_top_options, ScoredOption


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
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "today_options": [o.to_dict() for o in self.today_options],
            "tomorrow_draft": [o.to_dict() for o in self.tomorrow_draft],
            "day_after_draft": [o.to_dict() for o in self.day_after_draft],
            "recovery_score": self.recovery_score,
            "sleep_summary": self.sleep_summary,
            "equipment_profile": self.equipment_profile.value,
            "plan_date": self.plan_date.isoformat(),
        }


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
    
    # Get yesterday's strain
    yesterday_strain = await get_yesterday_strain(session, user_id)
    
    # === Generate Today's Options ===
    filtered = filter_options(
        all_options=ALL_OPTIONS,
        equipment_profile=equipment_profile,
        pain_locations=pain_locations,
        soreness=soreness,
        z4_last_7_days=z4_count,
        hours_since_last_z4=hours_since_z4,
        had_heavy_leg_yesterday=False,  # TODO: track
        recovery_score=recovery_score,
    )
    
    # Ensure Z3 is included if any run is allowed
    filtered = ensure_z3_included(filtered, ALL_OPTIONS)
    
    scored = score_options(
        options=filtered,
        recovery_score=recovery_score,
        yesterday_strain=yesterday_strain,
        soreness=soreness,
    )
    
    today_options = select_top_options(scored, count=3, ensure_variety=True)
    
    # === Tomorrow/Day After: Simple drafts ===
    # For MVP: use same options with slight adjustments
    tomorrow_draft = select_top_options(scored, count=2, ensure_variety=True)
    day_after_draft = select_top_options(scored, count=2, ensure_variety=True)
    
    plan = ThreeDayPlan(
        today_options=today_options,
        tomorrow_draft=tomorrow_draft,
        day_after_draft=day_after_draft,
        recovery_score=recovery_score,
        sleep_summary=sleep_summary,
        equipment_profile=equipment_profile,
        plan_date=today,
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
