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
        """Recovery=30, soreness=3 → mobility/rest options score higher due to DOMS boost."""
        scored = score_options(
            options=ALL_OPTIONS,
            recovery_score=30,
            yesterday_strain=15,
            soreness=3,  # Triggers leg DOMS, which boosts mobility
        )
        # Mobility/walking should rank high when leg DOMS is active
        low_impact_ranks = [
            s.rank for s in scored 
            if s.option.type in (WorkoutType.MOBILITY, WorkoutType.WALKING)
        ]
        assert any(r <= 5 for r in low_impact_ranks), "Low-impact should rank reasonably high at low recovery with DOMS"


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


# === Soft Scoring Tests (v0.5) ===

from whoop_coach.planner.scoring import (
    score_options_v2,
    select_diversified_options,
    ScoringContext,
    COST_FATIGUE_HARD,
    COST_REPEAT_MOD,
    COST_LEGS_DOMS_HEAVY,
    COST_Z4_LOW_REC,
)
from whoop_coach.planner.options import get_modality


class TestSoftScoringFatigue:
    """Test fatigue guardrail rules."""

    def test_fatigue_penalizes_hard_options(self):
        """recent_heavy_count_3d=2 → Z4 score drops below Z2/Z3."""
        ctx = ScoringContext(
            recovery_score=70,
            recent_heavy_count_3d=2,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z4 = next(s for s in scored if s.option.type == WorkoutType.RUN_Z4)
        z3 = next(s for s in scored if s.option.id == "run_z3_30")
        z2 = next(s for s in scored if s.option.id == "run_z2_30")
        
        # Z4 should have fatigue penalty, making it rank lower
        assert z3.net_score > z4.net_score, "Z3 should beat Z4 when fatigued"
        assert z2.net_score > z4.net_score, "Z2 should beat Z4 when fatigued"
        
        # Verify debug shows fatigue rule
        assert "fatigue_hard" in z4.debug.rules

    def test_fatigue_applies_medium_penalty_to_z3(self):
        """recent_heavy_count_3d=2 → Z3 gets medium penalty."""
        ctx = ScoringContext(
            recovery_score=70,
            recent_heavy_count_3d=2,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z3 = next(s for s in scored if s.option.id == "run_z3_30")
        
        # Verify debug shows fatigue_med rule
        assert "fatigue_med" in z3.debug.rules

    def test_no_fatigue_penalty_when_not_fatigued(self):
        """recent_heavy_count_3d=1 → no fatigue penalty."""
        ctx = ScoringContext(
            recovery_score=70,
            recent_heavy_count_3d=1,  # Below threshold
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z4 = next(s for s in scored if s.option.type == WorkoutType.RUN_Z4)
        
        # Should not have fatigue rules
        assert "fatigue_hard" not in z4.debug.rules
        assert "fatigue_med" not in z4.debug.rules


class TestSoftScoringLegDoms:
    """Test leg DOMS rules."""

    def test_leg_doms_penalizes_running(self):
        """last_leg_doms_high=True → mobility outranks run Z3."""
        ctx = ScoringContext(
            recovery_score=70,
            last_leg_doms_high=True,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        mobility = next(s for s in scored if s.option.type == WorkoutType.MOBILITY)
        z3 = next(s for s in scored if s.option.id == "run_z3_30")
        
        assert mobility.net_score > z3.net_score, "Mobility should beat Z3 when leg DOMS"
        assert "legs_doms" in z3.debug.rules

    def test_leg_doms_boosts_mobility(self):
        """last_leg_doms_high=True → mobility gets DOMS boost."""
        ctx = ScoringContext(
            recovery_score=70,
            last_leg_doms_high=True,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        mobility = next(s for s in scored if s.option.type == WorkoutType.MOBILITY)
        
        assert "doms_boost" in mobility.debug.rules

    def test_leg_doms_penalizes_barre(self):
        """last_leg_doms_high=True → barre gets leg doms penalty."""
        ctx = ScoringContext(
            recovery_score=70,
            last_leg_doms_high=True,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        barre = next(s for s in scored if s.option.type == WorkoutType.BARRE)
        
        assert "legs_doms" in barre.debug.rules


class TestSoftScoringAntiRepeat:
    """Test anti-repeat modality rules."""

    def test_antirepeat_penalizes_same_modality(self):
        """last_modality='strength' → strength loses to barre."""
        ctx = ScoringContext(
            recovery_score=70,
            last_modality="strength",
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        kb = next(s for s in scored if s.option.id == "kb_12")
        barre = next(s for s in scored if s.option.type == WorkoutType.BARRE)
        
        # Barre should be higher (no repeat penalty)
        assert barre.net_score > kb.net_score, "Barre should beat KB when last was strength"
        assert "repeat_mod" in kb.debug.rules

    def test_antirepeat_2day_penalty(self):
        """last_two_modalities=(run,run) → run gets extra penalty."""
        ctx = ScoringContext(
            recovery_score=70,
            last_modality="run",
            last_two_modalities=("run", "run"),
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z3 = next(s for s in scored if s.option.id == "run_z3_30")
        
        # Should have both repeat penalties
        assert "repeat_mod" in z3.debug.rules
        assert "repeat_2d" in z3.debug.rules

    def test_no_repeat_penalty_different_modality(self):
        """last_modality='strength' → run has no repeat penalty."""
        ctx = ScoringContext(
            recovery_score=70,
            last_modality="strength",
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z3 = next(s for s in scored if s.option.id == "run_z3_30")
        
        assert "repeat_mod" not in z3.debug.rules


class TestSoftScoringZ4:
    """Test Z4 'not default' rules."""

    def test_z4_not_default_mid_recovery(self):
        """recovery=70 → Z4 gets penalty, not primary."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z4 = next(s for s in scored if s.option.type == WorkoutType.RUN_Z4)
        
        # Z4 should not be rank 1
        assert z4.rank > 1, "Z4 should not be primary at recovery=70"
        assert "z4_low_rec" in z4.debug.rules

    def test_z4_great_day_bonus(self):
        """recovery=90, no fatigue, no doms → Z4 gets bonus."""
        ctx = ScoringContext(
            recovery_score=90,
            recent_heavy_count_3d=0,
            last_leg_doms_high=False,
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z4 = next(s for s in scored if s.option.type == WorkoutType.RUN_Z4)
        
        assert "z4_great" in z4.debug.rules
        # Z4 should rank highly on great days
        assert z4.rank <= 2, "Z4 should be top 2 on great day"

    def test_z4_no_bonus_when_fatigued(self):
        """recovery=90 but fatigued → no Z4 bonus."""
        ctx = ScoringContext(
            recovery_score=90,
            recent_heavy_count_3d=2,  # Fatigued
        )
        scored = score_options_v2(ALL_OPTIONS, ctx)
        
        z4 = next(s for s in scored if s.option.type == WorkoutType.RUN_Z4)
        
        # No great day bonus because fatigued
        assert "z4_great" not in z4.debug.rules
        # Should have fatigue penalty instead
        assert "fatigue_hard" in z4.debug.rules


class TestDiversifiedSelection:
    """Test diversified option selection."""

    def test_includes_easy_alternative(self):
        """Output includes mobility/walk/run_z2."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        selected = select_diversified_options(scored)
        
        easy_types = {WorkoutType.MOBILITY, WorkoutType.WALKING, WorkoutType.RUN_Z2}
        has_easy = any(s.option.type in easy_types for s in selected)
        
        assert has_easy, "Should include at least one easy option"

    def test_includes_different_modality(self):
        """Output has at least 2 distinct modalities."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        selected = select_diversified_options(scored)
        
        modalities = {get_modality(s.option) for s in selected}
        
        assert len(modalities) >= 2, "Should have at least 2 modalities"

    def test_returns_2_to_3_options(self):
        """Output has 2-3 options."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        selected = select_diversified_options(scored)
        
        assert 2 <= len(selected) <= 3, "Should return 2-3 options"

    def test_primary_is_best_score(self):
        """Primary option is the best scored."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        selected = select_diversified_options(scored)
        
        # Selected is sorted by score, so first should be best
        selected_ids = [s.option.id for s in selected]
        best_overall_id = scored[0].option.id
        
        assert best_overall_id in selected_ids, "Best option should be in selection"

    def test_no_duplicate_option_ids(self):
        """No duplicate option IDs in selection."""
        ctx = ScoringContext(recovery_score=70)
        scored = score_options_v2(ALL_OPTIONS, ctx)
        selected = select_diversified_options(scored)
        
        ids = [s.option.id for s in selected]
        
        assert len(ids) == len(set(ids)), "Should have no duplicate options"

