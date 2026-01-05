"""Workout matching logic — match pending logs to WHOOP workouts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class MatchCandidate:
    """A candidate WHOOP workout for matching."""

    workout_id: str
    start: datetime  # UTC-aware
    end: datetime  # UTC-aware
    workout_type: str
    strain: float
    duration_min: int
    score: float = 0.0  # Lower = better match

    @classmethod
    def from_whoop_workout(cls, workout: dict[str, Any]) -> "MatchCandidate":
        """Create from WHOOP API workout response."""
        start_str = workout.get("start", "")
        end_str = workout.get("end", "")

        # Parse ISO dates to UTC-aware datetime
        start = _parse_whoop_datetime(start_str)
        end = _parse_whoop_datetime(end_str)

        duration_min = int((end - start).total_seconds() / 60) if start and end else 0

        return cls(
            workout_id=str(workout.get("id", "")),
            start=start,
            end=end,
            workout_type=_get_workout_type(workout),
            strain=workout.get("score", {}).get("strain", 0.0),
            duration_min=duration_min,
        )


def _parse_whoop_datetime(iso_str: str) -> datetime:
    """Parse WHOOP ISO datetime to UTC-aware datetime."""
    if not iso_str:
        return datetime.min.replace(tzinfo=timezone.utc)

    # Handle both 'Z' and '+00:00' formats
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _get_workout_type(workout: dict[str, Any]) -> str:
    """Extract human-readable workout type from WHOOP workout."""
    sport = workout.get("sport_id", 0)
    # Common WHOOP sport IDs (partial list)
    sport_names = {
        0: "Activity",
        1: "Running",
        33: "Cycling",
        43: "Yoga",
        44: "Pilates",
        48: "Strength Training",
        52: "Walking",
        71: "HIIT",
        84: "Functional Fitness",
    }
    return sport_names.get(sport, f"Sport {sport}")


def find_candidates(
    workouts: list[dict[str, Any]],
    message_time: datetime,
    window_start_offset: timedelta = timedelta(hours=-3),
    window_end_offset: timedelta = timedelta(minutes=30),
) -> list[MatchCandidate]:
    """Find workouts whose end time falls within the matching window.

    Args:
        workouts: Raw WHOOP workout dicts from API
        message_time: UTC-aware timestamp from update.message.date
        window_start_offset: Start of window relative to message_time (default: -3h)
        window_end_offset: End of window relative to message_time (default: +30m)

    Returns:
        List of MatchCandidate objects whose end time is in window.
    """
    # Ensure message_time is UTC-aware
    if message_time.tzinfo is None:
        message_time = message_time.replace(tzinfo=timezone.utc)

    window_start = message_time + window_start_offset
    window_end = message_time + window_end_offset

    candidates = []
    for w in workouts:
        candidate = MatchCandidate.from_whoop_workout(w)
        # Check if workout.end falls in window
        if window_start <= candidate.end <= window_end:
            candidates.append(candidate)

    return candidates


def score_candidates(
    candidates: list[MatchCandidate],
    message_time: datetime,
) -> list[MatchCandidate]:
    """Score candidates by time distance, sorted best first.

    Primary scoring: abs(workout.end - message_time)
    Lower score = better match.

    Args:
        candidates: List of candidates to score
        message_time: UTC-aware timestamp

    Returns:
        Sorted list with scores set (best first).
    """
    if message_time.tzinfo is None:
        message_time = message_time.replace(tzinfo=timezone.utc)

    for c in candidates:
        # Score = seconds from message time (lower is better)
        delta = abs((c.end - message_time).total_seconds())
        c.score = delta

    return sorted(candidates, key=lambda c: c.score)


def match_workout(
    workouts: list[dict[str, Any]],
    message_time: datetime,
    extended_window: bool = False,
) -> tuple[list[MatchCandidate], str]:
    """Main matching function — find and score candidates.

    Args:
        workouts: Raw WHOOP workouts from API
        message_time: UTC-aware timestamp from message
        extended_window: If True, use +60min end offset (for /retry)

    Returns:
        Tuple of (scored candidates, status):
        - status: "none" | "single" | "multiple"
    """
    window_end_offset = timedelta(minutes=90 if extended_window else 30)

    candidates = find_candidates(
        workouts,
        message_time,
        window_end_offset=window_end_offset,
    )

    if not candidates:
        return [], "none"

    scored = score_candidates(candidates, message_time)

    if len(scored) == 1:
        return scored, "single"

    return scored, "multiple"
