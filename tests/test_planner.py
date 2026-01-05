"""Tests for planner module: constraints and scoring."""

import pytest

from whoop_coach.db.models import EquipmentProfile
from whoop_coach.planner.options import ALL_OPTIONS, WorkoutType
from whoop_coach.planner.constraints import filter_options, ensure_z3_included
from whoop_coach.planner.scoring import score_options, select_top_options


class TestEquipmentConstraints:
    """Test equipment-based filtering."""

    def test_home_full_allows_kettlebell(self):
        """Equipment=home_full → kettlebell options allowed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        kb_ids = [o.id for o in filtered if o.type == WorkoutType.KETTLEBELL]
        assert "kb_12" in kb_ids
        assert "kb_20" in kb_ids

    def test_travel_bands_no_kettlebell(self):
        """Equipment=travel_bands → kettlebell options removed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.TRAVEL_BANDS,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        kb_ids = [o.id for o in filtered if o.type == WorkoutType.KETTLEBELL]
        assert len(kb_ids) == 0
        # But bands should be allowed
        bands_ids = [o.id for o in filtered if o.type == WorkoutType.BANDS]
        assert "bands_strength" in bands_ids

    def test_travel_none_no_equipment(self):
        """Equipment=travel_none → kettlebell + bands removed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.TRAVEL_NONE,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        kb_ids = [o.id for o in filtered if o.type == WorkoutType.KETTLEBELL]
        bands_ids = [o.id for o in filtered if o.type == WorkoutType.BANDS]
        assert len(kb_ids) == 0
        assert len(bands_ids) == 0
        # Bodyweight should be allowed
        bw_ids = [o.id for o in filtered if o.type == WorkoutType.BODYWEIGHT]
        assert "bodyweight_strength" in bw_ids


class TestPainConstraints:
    """Test pain-based filtering."""

    def test_leg_pain_no_running(self):
        """Pain=['колено'] → all run options removed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=["колено"],
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        run_ids = [o.id for o in filtered if "run" in o.type.value]
        assert len(run_ids) == 0
        # Mobility should still be allowed
        assert any(o.id == "mobility" for o in filtered)

    def test_upper_body_pain_allows_running(self):
        """Pain=['плечо'] → running still allowed (not leg pain)."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=["плечо"],
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        run_ids = [o.id for o in filtered if "run" in o.type.value]
        assert len(run_ids) > 0


class TestSorenessConstraints:
    """Test soreness-based filtering."""

    def test_soreness_3_low_impact_only(self):
        """Soreness=3 → only mobility/barre/walking/light strength."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=3,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        # No running
        run_ids = [o.id for o in filtered if "run" in o.type.value]
        assert len(run_ids) == 0
        # No kb_20 (heavy)
        assert not any(o.id == "kb_20" for o in filtered)
        # But kb_12 is allowed
        assert any(o.id == "kb_12" for o in filtered)
        # Mobility allowed
        assert any(o.id == "mobility" for o in filtered)

    def test_soreness_2_no_z4(self):
        """Soreness=2 → Z4 removed, Z3 allowed if recovery good."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=2,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
            recovery_score=70,  # Good recovery
        )
        z4_ids = [o.id for o in filtered if o.type == WorkoutType.RUN_Z4]
        z3_ids = [o.id for o in filtered if o.type == WorkoutType.RUN_Z3]
        assert len(z4_ids) == 0
        assert len(z3_ids) > 0


class TestZ4Limits:
    """Test Z4 workout limits."""

    def test_z4_limit_reached(self):
        """Z4 count=2 → Z4 options removed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=2,  # Limit reached
            hours_since_last_z4=72,
            had_heavy_leg_yesterday=False,
        )
        z4_ids = [o.id for o in filtered if o.type == WorkoutType.RUN_Z4]
        assert len(z4_ids) == 0

    def test_z4_48h_cooldown(self):
        """Z4 < 48h ago → Z4 removed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=1,
            hours_since_last_z4=24,  # Only 24h since last Z4
            had_heavy_leg_yesterday=False,
        )
        z4_ids = [o.id for o in filtered if o.type == WorkoutType.RUN_Z4]
        assert len(z4_ids) == 0

    def test_z4_allowed_after_48h(self):
        """Z4 >= 48h ago → Z4 allowed."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=1,
            hours_since_last_z4=50,  # > 48h
            had_heavy_leg_yesterday=False,
        )
        z4_ids = [o.id for o in filtered if o.type == WorkoutType.RUN_Z4]
        assert len(z4_ids) > 0


class TestZ3Always:
    """Test Z3 is always included when running allowed."""

    def test_z3_always_included(self):
        """If run allowed, Z3 in options."""
        filtered = filter_options(
            all_options=ALL_OPTIONS,
            equipment_profile=EquipmentProfile.HOME_FULL,
            pain_locations=None,
            soreness=None,
            z4_last_7_days=0,
            hours_since_last_z4=None,
            had_heavy_leg_yesterday=False,
        )
        # Remove Z3 to test ensure_z3_included
        filtered_no_z3 = [o for o in filtered if o.type != WorkoutType.RUN_Z3]
        # But keep Z2 to simulate running allowed
        result = ensure_z3_included(filtered_no_z3, ALL_OPTIONS)
        z3_ids = [o.id for o in result if o.type == WorkoutType.RUN_Z3]
        assert len(z3_ids) >= 1, "Z3 should be added back by ensure_z3_included"


class TestScoring:
    """Test scoring logic."""

    def test_scoring_high_recovery(self):
        """Recovery=90 → Z4/high-benefit options score higher."""
        scored = score_options(
            options=ALL_OPTIONS,
            recovery_score=90,
            yesterday_strain=10,
            soreness=0,
        )
        # Best option should have positive score
        assert scored[0].net_score > 0
        # Z4 should be present and have positive score at high recovery
        z4_scores = [s for s in scored if s.option.type == WorkoutType.RUN_Z4]
        assert len(z4_scores) > 0, "Z4 should be in options"
        assert z4_scores[0].net_score > 0, "Z4 should have positive net score at high recovery"

    def test_scoring_low_recovery(self):
        """Recovery=30 → mobility/rest options score higher."""
        scored = score_options(
            options=ALL_OPTIONS,
            recovery_score=30,
            yesterday_strain=15,
            soreness=2,
        )
        # Mobility/walking should rank high
        low_impact_ranks = [
            s.rank for s in scored 
            if s.option.type in (WorkoutType.MOBILITY, WorkoutType.WALKING)
        ]
        assert any(r <= 3 for r in low_impact_ranks), "Low-impact should rank high at low recovery"


class TestOptionSelection:
    """Test option selection logic."""

    def test_select_top_with_variety(self):
        """Selection ensures at least one run and one non-run option."""
        scored = score_options(
            options=ALL_OPTIONS,
            recovery_score=70,
            yesterday_strain=10,
            soreness=0,
        )
        top3 = select_top_options(scored, count=3, ensure_variety=True)
        
        has_run = any("run" in o.option.type.value for o in top3)
        has_non_run = any("run" not in o.option.type.value for o in top3)
        
        assert has_run, "Should include at least one run option"
        assert has_non_run, "Should include at least one non-run option"
