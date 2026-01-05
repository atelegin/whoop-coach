"""Tests for workout matching logic."""

from datetime import datetime, timedelta, timezone

import pytest

from whoop_coach.matching import (
    MatchCandidate,
    find_candidates,
    match_workout,
    score_candidates,
)


def _make_workout(
    workout_id: str,
    end_offset_minutes: int,
    base_time: datetime,
    sport_id: int = 48,
    strain: float = 12.5,
) -> dict:
    """Helper to create mock WHOOP workout."""
    end = base_time + timedelta(minutes=end_offset_minutes)
    start = end - timedelta(minutes=30)  # 30 min workout
    return {
        "id": workout_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sport_id": sport_id,
        "score": {"strain": strain},
    }


class TestFindCandidates:
    """Test find_candidates function."""

    def test_find_candidates_in_window(self):
        """Workout ending in window is included."""
        now = datetime.now(timezone.utc)
        workouts = [
            _make_workout("w1", -60, now),  # ended 1h ago — in window
            _make_workout("w2", -180, now),  # ended 3h ago — at edge
        ]
        candidates = find_candidates(workouts, now)
        ids = [c.workout_id for c in candidates]
        assert "w1" in ids

    def test_find_candidates_outside_window(self):
        """Workout ending outside window is excluded."""
        now = datetime.now(timezone.utc)
        workouts = [
            _make_workout("w1", -240, now),  # ended 4h ago — outside
        ]
        candidates = find_candidates(workouts, now)
        assert len(candidates) == 0

    def test_find_candidates_future_window(self):
        """Workout ending slightly in future (within +30m) is included."""
        now = datetime.now(timezone.utc)
        workouts = [
            _make_workout("w1", 15, now),  # ends in 15 min — in window
            _make_workout("w2", 45, now),  # ends in 45 min — outside
        ]
        candidates = find_candidates(workouts, now)
        ids = [c.workout_id for c in candidates]
        assert "w1" in ids
        assert "w2" not in ids


class TestScoreCandidates:
    """Test score_candidates function."""

    def test_score_candidates_by_time_distance(self):
        """Candidates are sorted by time distance (closest first)."""
        now = datetime.now(timezone.utc)
        c1 = MatchCandidate(
            workout_id="w1",
            start=now - timedelta(minutes=60),
            end=now - timedelta(minutes=30),  # 30 min ago
            workout_type="Strength",
            strain=10.0,
            duration_min=30,
        )
        c2 = MatchCandidate(
            workout_id="w2",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=5),  # 5 min ago — closer
            workout_type="Strength",
            strain=12.0,
            duration_min=15,
        )
        scored = score_candidates([c1, c2], now)
        assert scored[0].workout_id == "w2"
        assert scored[1].workout_id == "w1"
        assert scored[0].score < scored[1].score

    def test_matching_prefers_closest_end_time(self):
        """When two are close, the one ending closer to message wins."""
        now = datetime.now(timezone.utc)
        c1 = MatchCandidate(
            workout_id="w1",
            start=now - timedelta(minutes=35),
            end=now - timedelta(minutes=10),
            workout_type="Strength",
            strain=10.0,
            duration_min=25,
        )
        c2 = MatchCandidate(
            workout_id="w2",
            start=now - timedelta(minutes=30),
            end=now - timedelta(minutes=8),  # 2 min closer
            workout_type="Yoga",
            strain=8.0,
            duration_min=22,
        )
        scored = score_candidates([c1, c2], now)
        assert scored[0].workout_id == "w2"


class TestMatchWorkout:
    """Test main match_workout function."""

    def test_single_candidate_auto_match(self):
        """Single candidate returns status='single'."""
        now = datetime.now(timezone.utc)
        workouts = [_make_workout("w1", -30, now)]
        candidates, status = match_workout(workouts, now)
        assert status == "single"
        assert len(candidates) == 1
        assert candidates[0].workout_id == "w1"

    def test_multiple_candidates_returns_list(self):
        """Multiple candidates returns status='multiple'."""
        now = datetime.now(timezone.utc)
        workouts = [
            _make_workout("w1", -30, now),
            _make_workout("w2", -60, now),
        ]
        candidates, status = match_workout(workouts, now)
        assert status == "multiple"
        assert len(candidates) == 2

    def test_no_candidates_returns_none(self):
        """No candidates returns status='none'."""
        now = datetime.now(timezone.utc)
        workouts = [_make_workout("w1", -240, now)]  # 4h ago — outside
        candidates, status = match_workout(workouts, now)
        assert status == "none"
        assert len(candidates) == 0

    def test_extended_window_for_retry(self):
        """Extended window includes workout at +60m."""
        now = datetime.now(timezone.utc)
        workouts = [_make_workout("w1", 60, now)]  # ends in 1h
        candidates_normal, _ = match_workout(workouts, now, extended_window=False)
        candidates_extended, _ = match_workout(workouts, now, extended_window=True)
        assert len(candidates_normal) == 0
        assert len(candidates_extended) == 1
