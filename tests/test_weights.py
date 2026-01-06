"""Tests for KB weight assignment logic."""

import pytest
from whoop_coach.planner.weights import (
    assign_kb_weights,
    format_kb_weights_ru,
    UserKbCaps,
    HEAVY_TAGS,
)


class TestAssignKbWeights:
    """Tests for assign_kb_weights function."""

    def test_overhead_forces_overhead_max(self):
        """Overhead tag uses kb_overhead_max_kg."""
        user = UserKbCaps(kb_overhead_max_kg=12, kb_heavy_kg=20, kb_swing_kg=20)
        weights = assign_kb_weights(["overhead"], user)
        
        assert weights == {"overhead_kg": 12}

    def test_swing_uses_user_toggle_12(self):
        """Swing tag uses kb_swing_kg when set to 12."""
        user = UserKbCaps(kb_swing_kg=12)
        weights = assign_kb_weights(["swing"], user)
        
        assert weights == {"swing_kg": 12}

    def test_swing_uses_user_toggle_20(self):
        """Swing tag uses kb_swing_kg when set to 20."""
        user = UserKbCaps(kb_swing_kg=20)
        weights = assign_kb_weights(["swing"], user)
        
        assert weights == {"swing_kg": 20}

    def test_heavy_patterns_use_heavy_pull(self):
        """Pull tag uses kb_heavy_kg."""
        user = UserKbCaps(kb_heavy_kg=20)
        weights = assign_kb_weights(["pull"], user)
        
        assert weights == {"heavy_kg": 20}

    def test_heavy_patterns_use_heavy_squat(self):
        """Squat tag uses kb_heavy_kg."""
        user = UserKbCaps(kb_heavy_kg=20)
        weights = assign_kb_weights(["squat"], user)
        
        assert weights == {"heavy_kg": 20}

    def test_heavy_patterns_use_heavy_carry(self):
        """Carry tag uses kb_heavy_kg."""
        user = UserKbCaps(kb_heavy_kg=20)
        weights = assign_kb_weights(["carry"], user)
        
        assert weights == {"heavy_kg": 20}

    def test_multiple_tags_return_multiple_weights(self):
        """Multiple tags return multiple weights."""
        user = UserKbCaps(kb_overhead_max_kg=12, kb_heavy_kg=20, kb_swing_kg=20)
        weights = assign_kb_weights(["overhead", "swing", "pull"], user)
        
        assert weights == {
            "overhead_kg": 12,
            "swing_kg": 20,
            "heavy_kg": 20,
        }

    def test_empty_tags_return_empty_dict(self):
        """Empty tags return empty dict."""
        user = UserKbCaps()
        weights = assign_kb_weights([], user)
        
        assert weights == {}

    def test_unknown_tags_return_empty_dict(self):
        """Unknown tags return empty dict."""
        user = UserKbCaps()
        weights = assign_kb_weights(["unknown", "foo"], user)
        
        assert weights == {}

    def test_case_insensitive(self):
        """Tags are case-insensitive."""
        user = UserKbCaps(kb_swing_kg=12)
        weights = assign_kb_weights(["SWING", "Overhead"], user)
        
        assert "swing_kg" in weights
        assert "overhead_kg" in weights

    def test_heavy_tags_constant(self):
        """HEAVY_TAGS contains expected values."""
        assert HEAVY_TAGS == {"pull", "squat", "carry"}


class TestFormatKbWeightsRu:
    """Tests for format_kb_weights_ru function."""

    def test_format_single_overhead(self):
        """Format single overhead weight."""
        result = format_kb_weights_ru({"overhead_kg": 12})
        
        assert result == "над головой 12 кг"

    def test_format_single_swing(self):
        """Format single swing weight."""
        result = format_kb_weights_ru({"swing_kg": 20})
        
        assert result == "свинг 20 кг"

    def test_format_single_heavy(self):
        """Format single heavy weight."""
        result = format_kb_weights_ru({"heavy_kg": 20})
        
        assert result == "тяга/присед/переноски 20 кг"

    def test_format_multiple(self):
        """Format multiple weights."""
        result = format_kb_weights_ru({
            "overhead_kg": 12,
            "swing_kg": 20,
        })
        
        assert "над головой 12 кг" in result
        assert "свинг 20 кг" in result
        assert ";" in result

    def test_format_all_three(self):
        """Format all three weight types."""
        result = format_kb_weights_ru({
            "overhead_kg": 12,
            "swing_kg": 20,
            "heavy_kg": 20,
        })
        
        assert result == "над головой 12 кг; свинг 20 кг; тяга/присед/переноски 20 кг"

    def test_format_empty(self):
        """Empty weights return empty string."""
        result = format_kb_weights_ru({})
        
        assert result == ""
