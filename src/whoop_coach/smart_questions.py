"""Smart questions logic for unattributed workouts and morning prompts.

Implements NeedMoreInfoScore calculation per spec section 9:
- Score >= 2 → ask RPE
- Score >= 3 → ask RPE + "где болит"
"""

from datetime import datetime, time, timedelta, timezone
from typing import Any

# === Risky Sport IDs (per WHOOP API docs) ===

# Always-risky (+2 points) - ski, hiking, climbing, etc.
RISKY_ALWAYS: set[int] = {
    29,   # Skiing
    47,   # Cross Country Skiing
    52,   # Hiking/Rucking
    91,   # Snowboarding
    60,   # Rock Climbing
    57,   # Mountain Biking
    94,   # Obstacle Course Racing
    110,  # Parkour
    86,   # Skateboarding
    92,   # Motocross
}

# Contact/impact sports (+1 point)
RISKY_CONTACT: set[int] = {
    17,   # Basketball
    30,   # Soccer
    27,   # Rugby
    21,   # Football
    56,   # Martial Arts
    39,   # Boxing
    127,  # Kickboxing
    38,   # Wrestling
    98,   # Jiu Jitsu
    84,   # Jumping Rope
    96,   # HIIT
}

# Fallback keywords when sport_id is not available (deprecated after 09/2025)
RISKY_ALWAYS_KEYWORDS: set[str] = {
    "skiing", "cross country", "hiking", "rucking", "snowboard",
    "rock climbing", "mountain biking", "obstacle", "parkour",
    "skateboard", "motocross",
}

RISKY_CONTACT_KEYWORDS: set[str] = {
    "basketball", "soccer", "rugby", "football", "martial",
    "boxing", "kickbox", "wrestling", "jiu jitsu", "hiit", "jump",
}

# Default strain threshold if no user history
DEFAULT_STRAIN_THRESHOLD = 14.0

# Late workout threshold (local time)
LATE_HOUR = 19


def _get_sport_key(workout: dict[str, Any]) -> int | str:
    """Get normalized sport key for counting unique types.
    
    Returns sport_id if available, otherwise sport_name.lower().
    """
    sport_id = workout.get("sport_id")
    if sport_id is not None:
        return sport_id
    sport_name = workout.get("sport_name", "unknown")
    return sport_name.lower() if sport_name else "unknown"


def _get_sport_name(workout: dict[str, Any]) -> str:
    """Get sport name from workout, lowercased for keyword matching."""
    return (workout.get("sport_name") or "").lower()


def _is_risky_always(workout: dict[str, Any]) -> bool:
    """Check if workout is in always-risky category (+2 points)."""
    sport_id = workout.get("sport_id")
    if sport_id is not None and sport_id in RISKY_ALWAYS:
        return True
    # Fallback to sport_name
    name = _get_sport_name(workout)
    return any(kw in name for kw in RISKY_ALWAYS_KEYWORDS)


def _is_risky_contact(workout: dict[str, Any]) -> bool:
    """Check if workout is in contact/impact category (+1 point)."""
    sport_id = workout.get("sport_id")
    if sport_id is not None and sport_id in RISKY_CONTACT:
        return True
    # Fallback to sport_name
    name = _get_sport_name(workout)
    return any(kw in name for kw in RISKY_CONTACT_KEYWORDS)


def _get_duration_minutes(workout: dict[str, Any]) -> int:
    """Calculate duration from start/end times."""
    start_str = workout.get("start", "")
    end_str = workout.get("end", "")
    
    if not start_str or not end_str:
        return 0
    
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        return int((end - start).total_seconds() / 60)
    except (ValueError, TypeError):
        return 0


def _get_local_end_hour(workout: dict[str, Any]) -> int:
    """Get workout end hour in local time.
    
    Uses timezone_offset from workout if available, else Europe/Berlin (UTC+1/+2).
    """
    end_str = workout.get("end", "")
    if not end_str:
        return 12  # Default to noon (not late)
    
    try:
        end_utc = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        
        # Try to use timezone_offset from workout (in format "-05:00" or similar)
        tz_offset = workout.get("timezone_offset", "")
        if tz_offset:
            # Parse timezone offset like "-05:00" or "+02:00"
            try:
                sign = 1 if tz_offset[0] == "+" else -1
                hours = int(tz_offset[1:3])
                minutes = int(tz_offset[4:6]) if len(tz_offset) > 4 else 0
                offset = timedelta(hours=sign * hours, minutes=sign * minutes)
                local_time = end_utc + offset
                return local_time.hour
            except (ValueError, IndexError):
                pass
        
        # Fallback: Europe/Berlin ~ UTC+1 (winter) / UTC+2 (summer)
        # Simplified: assume UTC+1 for now
        local_time = end_utc + timedelta(hours=1)
        return local_time.hour
    except (ValueError, TypeError):
        return 12


def compute_need_more_info_score(
    workout: dict[str, Any],
    user_median_strain: float | None = None,
    workout_type_count: dict[int | str, int] | None = None,
    had_heavy_planned_yesterday: bool = False,
) -> int:
    """Compute NeedMoreInfoScore for an unattributed workout.
    
    Per spec section 9:
    - +2 if type ∈ always-risky (ski, hiking, etc.)
    - +1 if type ∈ contact sports
    - +1 if duration > 90 min
    - +1 if strain > user median (or default threshold)
    - +1 if new type (seen < 3 times)
    - +1 if ended late (after 19:00 local time)
    - +1 if heavy planned workout yesterday
    
    Returns:
        Score (0+), or -1 if workout is not scored yet (score_state != "SCORED")
    """
    # Gate: only process scored workouts
    score_state = workout.get("score_state", "")
    if score_state != "SCORED":
        return -1  # Skip unscored workouts
    
    score_data = workout.get("score", {})
    if not score_data:
        return -1
    
    points = 0
    
    # +2 for always-risky sports
    if _is_risky_always(workout):
        points += 2
    # +1 for contact sports (not cumulative with always-risky)
    elif _is_risky_contact(workout):
        points += 1
    
    # +1 for duration > 90 min
    duration = _get_duration_minutes(workout)
    if duration > 90:
        points += 1
    
    # +1 for high strain
    strain = score_data.get("strain", 0.0)
    threshold = user_median_strain or DEFAULT_STRAIN_THRESHOLD
    if strain > threshold:
        points += 1
    
    # +1 for new/rare type
    if workout_type_count is not None:
        sport_key = _get_sport_key(workout)
        count = workout_type_count.get(sport_key, 0)
        if count < 3:
            points += 1
    
    # +1 if ended late (after 19:00 local)
    end_hour = _get_local_end_hour(workout)
    if end_hour >= LATE_HOUR:
        points += 1
    
    # +1 if heavy planned yesterday
    if had_heavy_planned_yesterday:
        points += 1
    
    return points


def should_ask_rpe(score: int) -> bool:
    """Check if RPE should be asked based on NeedMoreInfoScore."""
    return score >= 2


def should_ask_pain_locations(score: int) -> bool:
    """Check if pain locations should be asked based on NeedMoreInfoScore."""
    return score >= 3


def should_prompt_morning(
    had_planned_workout_yesterday: bool,
    had_high_score_unattributed: bool,
    had_risky_day: bool,
) -> bool:
    """Determine if morning soreness/pain prompt is needed.
    
    Per spec section 5.4: ask when:
    - Yesterday had a planned workout (video/run)
    - Or had unattributed workout with high NeedMoreInfoScore
    - Or had "risky" day (ski/hike/very high strain)
    """
    return (
        had_planned_workout_yesterday
        or had_high_score_unattributed
        or had_risky_day
    )


def should_skip_pain_prompt(soreness: int) -> bool:
    """Check if pain locations prompt should be skipped.
    
    If soreness == 0, no need to ask about pain locations.
    """
    return soreness == 0
