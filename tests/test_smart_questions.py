"""Tests for smart questions module."""

import pytest
from datetime import datetime, timezone, timedelta

from whoop_coach.smart_questions import (
    RISKY_ALWAYS,
    RISKY_CONTACT,
    RISKY_ALWAYS_KEYWORDS,
    compute_need_more_info_score,
    should_ask_rpe,
    should_ask_pain_locations,
    should_skip_pain_prompt,
    _is_risky_always,
    _is_risky_contact,
    _get_duration_minutes,
    _get_local_end_hour,
)


def _make_workout(
    sport_id: int | None = 48,
    sport_name: str = "Strength Training",
    duration_min: int = 45,
    strain: float = 12.0,
    score_state: str = "SCORED",
    end_hour_utc: int = 10,
    timezone_offset: str | None = None,
) -> dict:
    """Helper to create mock WHOOP workout."""
    now = datetime.now(timezone.utc).replace(hour=end_hour_utc, minute=0, second=0)
    start = now - timedelta(minutes=duration_min)
    
    workout = {
        "id": "123456",
        "start": start.isoformat(),
        "end": now.isoformat(),
        "score_state": score_state,
        "score": {
            "strain": strain,
            "average_heart_rate": 140,
        },
    }
    
    if sport_id is not None:
        workout["sport_id"] = sport_id
    if sport_name:
        workout["sport_name"] = sport_name
    if timezone_offset:
        workout["timezone_offset"] = timezone_offset
        
    return workout


class TestRiskySportDetection:
    """Test sport risk classification."""

    def test_skiing_is_always_risky(self):
        """Skiing (sport_id=29) should be always-risky."""
        workout = _make_workout(sport_id=29, sport_name="Skiing")
        assert _is_risky_always(workout) is True
        assert _is_risky_contact(workout) is False

    def test_snowboarding_is_always_risky(self):
        """Snowboarding (sport_id=91) should be always-risky."""
        workout = _make_workout(sport_id=91, sport_name="Snowboarding")
        assert _is_risky_always(workout) is True

    def test_hiking_is_always_risky(self):
        """Hiking (sport_id=52) should be always-risky."""
        workout = _make_workout(sport_id=52, sport_name="Hiking/Rucking")
        assert _is_risky_always(workout) is True

    def test_cross_country_skiing_is_always_risky(self):
        """Cross Country Skiing (sport_id=47) should be always-risky."""
        workout = _make_workout(sport_id=47, sport_name="Cross Country Skiing")
        assert _is_risky_always(workout) is True

    def test_basketball_is_contact_risky(self):
        """Basketball (sport_id=17) should be contact-risky."""
        workout = _make_workout(sport_id=17, sport_name="Basketball")
        assert _is_risky_always(workout) is False
        assert _is_risky_contact(workout) is True

    def test_hiit_is_contact_risky(self):
        """HIIT (sport_id=96) should be contact-risky."""
        workout = _make_workout(sport_id=96, sport_name="HIIT")
        assert _is_risky_contact(workout) is True

    def test_strength_not_risky(self):
        """Strength training should not be risky."""
        workout = _make_workout(sport_id=48, sport_name="Strength Training")
        assert _is_risky_always(workout) is False
        assert _is_risky_contact(workout) is False

    def test_fallback_to_sport_name_keywords(self):
        """When sport_id is None, fallback to sport_name keywords."""
        # Skiing in name but no sport_id (deprecated after 09/2025)
        workout = _make_workout(sport_id=None, sport_name="Skiing - Alpine")
        assert _is_risky_always(workout) is True

    def test_fallback_hiking_keyword(self):
        """Hiking keyword detected in sport_name."""
        workout = _make_workout(sport_id=None, sport_name="Hiking Trail Run")
        assert _is_risky_always(workout) is True

    def test_unknown_sport_not_risky(self):
        """Unknown sport is not risky by default."""
        workout = _make_workout(sport_id=999, sport_name="Unknown Activity")
        assert _is_risky_always(workout) is False
        assert _is_risky_contact(workout) is False


class TestNeedMoreInfoScore:
    """Test NeedMoreInfoScore calculation."""

    def test_unscored_workout_returns_minus_one(self):
        """Unscored workout should return -1."""
        workout = _make_workout(score_state="PENDING_SCORE")
        score = compute_need_more_info_score(workout)
        assert score == -1

    def test_always_risky_gives_2_points(self):
        """Always-risky sport gives +2 points."""
        workout = _make_workout(sport_id=29)  # Skiing
        score = compute_need_more_info_score(workout)
        assert score >= 2

    def test_contact_gives_1_point(self):
        """Contact sport gives +1 point."""
        workout = _make_workout(sport_id=17)  # Basketball
        score = compute_need_more_info_score(workout)
        # Base score from contact sport
        assert score >= 1

    def test_duration_over_90_gives_1_point(self):
        """Duration > 90 min gives +1 point."""
        workout = _make_workout(sport_id=48, duration_min=100)
        score_long = compute_need_more_info_score(workout)
        
        workout_short = _make_workout(sport_id=48, duration_min=60)
        score_short = compute_need_more_info_score(workout_short)
        
        assert score_long > score_short

    def test_high_strain_gives_1_point(self):
        """Strain above threshold gives +1 point."""
        workout_high = _make_workout(sport_id=48, strain=18.0)
        workout_low = _make_workout(sport_id=48, strain=10.0)
        
        score_high = compute_need_more_info_score(workout_high)
        score_low = compute_need_more_info_score(workout_low)
        
        assert score_high > score_low

    def test_new_type_gives_1_point(self):
        """New/rare type gives +1 point."""
        workout = _make_workout(sport_id=48)
        
        # No history = new type
        score_new = compute_need_more_info_score(workout, workout_type_count={})
        
        # Seen 5 times = not new
        score_known = compute_need_more_info_score(
            workout, workout_type_count={48: 5}
        )
        
        assert score_new > score_known

    def test_late_workout_gives_1_point(self):
        """Workout ending after 19:00 local gives +1 point."""
        # 19:00 UTC + Berlin offset = 20:00 local
        workout_late = _make_workout(sport_id=48, end_hour_utc=19)
        workout_early = _make_workout(sport_id=48, end_hour_utc=10)
        
        score_late = compute_need_more_info_score(workout_late)
        score_early = compute_need_more_info_score(workout_early)
        
        assert score_late > score_early

    def test_heavy_yesterday_gives_1_point(self):
        """Heavy planned workout yesterday gives +1 point."""
        workout = _make_workout(sport_id=48)
        
        score_heavy = compute_need_more_info_score(
            workout, had_heavy_planned_yesterday=True
        )
        score_normal = compute_need_more_info_score(
            workout, had_heavy_planned_yesterday=False
        )
        
        assert score_heavy > score_normal

    def test_combined_score_ski_long_high_strain(self):
        """Combined: ski + 100min + high strain = high score."""
        workout = _make_workout(
            sport_id=29,  # Skiing (+2)
            duration_min=100,  # > 90 min (+1)
            strain=18.0,  # High (+1)
        )
        score = compute_need_more_info_score(workout)
        assert score >= 4


class TestDecisionFunctions:
    """Test decision functions."""

    def test_should_ask_rpe_at_score_2(self):
        """Ask RPE when score >= 2."""
        assert should_ask_rpe(2) is True
        assert should_ask_rpe(3) is True
        assert should_ask_rpe(1) is False
        assert should_ask_rpe(0) is False

    def test_should_ask_pain_at_score_3(self):
        """Ask pain when score >= 3."""
        assert should_ask_pain_locations(3) is True
        assert should_ask_pain_locations(4) is True
        assert should_ask_pain_locations(2) is False

    def test_skip_pain_when_soreness_zero(self):
        """Skip pain prompt when soreness == 0."""
        assert should_skip_pain_prompt(0) is True
        assert should_skip_pain_prompt(1) is False
        assert should_skip_pain_prompt(2) is False
        assert should_skip_pain_prompt(3) is False


class TestDurationCalculation:
    """Test duration calculation from timestamps."""

    def test_duration_minutes_calculated(self):
        """Duration calculated from start/end."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=45)
        
        workout = {
            "start": start.isoformat(),
            "end": now.isoformat(),
        }
        
        duration = _get_duration_minutes(workout)
        assert duration == 45

    def test_missing_timestamps_returns_zero(self):
        """Missing timestamps return 0."""
        assert _get_duration_minutes({}) == 0
        assert _get_duration_minutes({"start": ""}) == 0


class TestTimezoneHandling:
    """Test late workout timezone handling."""

    def test_uses_timezone_offset_from_workout(self):
        """Uses timezone_offset from workout if available."""
        # UTC 17:00 with +02:00 offset = 19:00 local
        workout = _make_workout(end_hour_utc=17, timezone_offset="+02:00")
        hour = _get_local_end_hour(workout)
        assert hour == 19

    def test_falls_back_to_berlin(self):
        """Falls back to Europe/Berlin (UTC+1) when no offset."""
        # UTC 18:00 with Berlin offset = 19:00 local
        workout = _make_workout(end_hour_utc=18, timezone_offset=None)
        hour = _get_local_end_hour(workout)
        assert hour == 19

    def test_missing_end_returns_noon(self):
        """Missing end time returns 12 (not late)."""
        workout = {"score_state": "SCORED", "score": {}}
        hour = _get_local_end_hour(workout)
        assert hour == 12
