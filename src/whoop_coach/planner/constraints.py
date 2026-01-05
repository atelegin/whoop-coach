"""Hard constraints for workout filtering.

Implements spec section 10: safety rules that completely block certain options.
"""

from __future__ import annotations

from whoop_coach.db.models import EquipmentProfile
from whoop_coach.planner.options import (
    WorkoutOption,
    WorkoutType,
    EquipmentRequired,
    ImpactLevel,
)


# Pain locations that block running
LEG_PAIN_LOCATIONS = {"колено", "икры", "бедро"}


def filter_options(
    all_options: list[WorkoutOption],
    equipment_profile: EquipmentProfile,
    pain_locations: list[str] | None,
    soreness: int | None,
    z4_last_7_days: int,
    hours_since_last_z4: float | None,
    had_heavy_leg_yesterday: bool,
    recovery_score: int | None = None,
) -> list[WorkoutOption]:
    """Filter out prohibited options based on hard constraints.
    
    Args:
        all_options: All available workout options
        equipment_profile: User's current equipment availability
        pain_locations: List of pain location strings (e.g., ["колено"])
        soreness: Soreness level 0-3
        z4_last_7_days: Count of Z4 workouts in last 7 days
        hours_since_last_z4: Hours since last Z4 workout, or None
        had_heavy_leg_yesterday: Whether there was heavy leg load yesterday
        recovery_score: WHOOP recovery score 0-100
        
    Returns:
        Filtered list of allowed workout options
    """
    allowed = []
    pain_set = set(pain_locations or [])
    has_leg_pain = bool(pain_set & LEG_PAIN_LOCATIONS)
    soreness = soreness or 0
    
    for opt in all_options:
        # === Equipment constraints ===
        if equipment_profile == EquipmentProfile.TRAVEL_BANDS:
            # No kettlebell in travel_bands mode
            if opt.equipment_required == EquipmentRequired.KETTLEBELL:
                continue
        elif equipment_profile == EquipmentProfile.TRAVEL_NONE:
            # No kettlebell or bands in travel_none mode
            if opt.equipment_required in (
                EquipmentRequired.KETTLEBELL,
                EquipmentRequired.BANDS,
            ):
                continue
        
        # === Pain constraints ===
        # Leg pain → no running
        if has_leg_pain:
            if opt.type in (WorkoutType.RUN_Z2, WorkoutType.RUN_Z3, WorkoutType.RUN_Z4):
                continue
        
        # === Soreness constraints ===
        if soreness >= 3:
            # soreness=3 → only mobility/walking/light barre
            if opt.type in (
                WorkoutType.RUN_Z2,
                WorkoutType.RUN_Z3,
                WorkoutType.RUN_Z4,
            ):
                continue
            # No heavy kettlebell
            if opt.id == "kb_20":
                continue
        
        if soreness >= 2:
            # soreness=2 → no Z4
            if opt.type == WorkoutType.RUN_Z4:
                continue
            # Z3 only if no leg pain and recovery not low
            if opt.type == WorkoutType.RUN_Z3:
                if has_leg_pain:
                    continue
                if recovery_score is not None and recovery_score < 33:
                    continue
        
        # === Z4 limits ===
        if opt.type == WorkoutType.RUN_Z4:
            # Max 2 Z4 per 7 days
            if z4_last_7_days >= 2:
                continue
            # At least 48h between Z4
            if hours_since_last_z4 is not None and hours_since_last_z4 < 48:
                continue
            # No Z4 after heavy leg day
            if had_heavy_leg_yesterday:
                continue
        
        allowed.append(opt)
    
    return allowed


def ensure_z3_included(
    filtered_options: list[WorkoutOption],
    all_options: list[WorkoutOption],
) -> list[WorkoutOption]:
    """Ensure at least one Z3 run option is included if running is allowed.
    
    Per spec: Z3 is the default base run, should always be available if any run is.
    """
    has_any_run = any(
        opt.type in (WorkoutType.RUN_Z2, WorkoutType.RUN_Z3, WorkoutType.RUN_Z4)
        for opt in filtered_options
    )
    
    has_z3 = any(opt.type == WorkoutType.RUN_Z3 for opt in filtered_options)
    
    if has_any_run and not has_z3:
        # Add Z3 30min as minimum
        z3_opt = next(
            (o for o in all_options if o.id == "run_z3_30"),
            None,
        )
        if z3_opt:
            filtered_options = [z3_opt] + filtered_options
    
    return filtered_options
