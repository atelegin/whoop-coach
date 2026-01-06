"""Soft scoring for workout options.

Implements spec section 11: benefit/cost optimization.
v0.5: Added guardrail-based soft scoring with fatigue, anti-repeat,
      leg DOMS, and Z4 "not default" rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from whoop_coach.planner.options import WorkoutOption, WorkoutType, get_modality


# === Soft Scoring Constants ===
# Base benefits by (modality, zone)
BASE_BENEFITS: dict[tuple[str, str | None], float] = {
    ("run", "Z4"): 35.0,
    ("run", "Z3"): 30.0,
    ("run", "Z2"): 22.0,
    ("strength", None): 28.0,
    ("barre", None): 26.0,
    ("mobility", None): 20.0,
    ("walk", None): 18.0,
}

# Fatigue guardrail costs
COST_FATIGUE_HARD = 25.0
COST_FATIGUE_MED = 10.0

# Anti-repeat costs
COST_REPEAT_MOD = 6.0
COST_REPEAT_2D = 12.0

# Leg DOMS costs/benefits
COST_LEGS_DOMS_HEAVY = 20.0
COST_LEGS_DOMS_BARRE = 10.0
BENEFIT_DOMS_BOOST = 8.0

# Z4 "not default" costs/benefits
COST_Z4_LOW_REC = 15.0
BENEFIT_Z4_GREAT = 8.0

# Recovery thresholds
RECOVERY_LOW_THRESHOLD = 75
RECOVERY_HIGH_THRESHOLD = 85

# "Easy" modalities for diversification
EASY_TYPES = {WorkoutType.MOBILITY, WorkoutType.WALKING, WorkoutType.RUN_Z2}


@dataclass
class ScoringContext:
    """Context for soft scoring rules."""
    
    recovery_score: int = 50
    soreness: int = 0
    recent_heavy_count_3d: int = 0
    last_leg_doms_high: bool = False
    last_modality: str | None = None
    last_two_modalities: tuple[str, str] | None = None


@dataclass
class ScoringDebug:
    """Compact debug info for scoring rules applied."""
    
    benefit: float
    cost: float
    net_score: float
    rules: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to compact dict for JSON."""
        return {
            "b": round(self.benefit, 1),
            "c": round(self.cost, 1),
            "n": round(self.net_score, 1),
            "r": self.rules,
        }


@dataclass
class ScoredOption:
    """Workout option with computed scores."""
    
    option: WorkoutOption
    benefit: float
    cost: float
    net_score: float
    rank: int = 0
    debug: ScoringDebug | None = None
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        result = {
            "id": self.option.id,
            "name_ru": self.option.name_ru,
            "benefit": round(self.benefit, 2),
            "cost": round(self.cost, 2),
            "net_score": round(self.net_score, 2),
            "rank": self.rank,
        }
        if self.debug:
            result["debug"] = self.debug.to_dict()
        return result


def _get_base_benefit(opt: WorkoutOption) -> float:
    """Get base benefit for an option from lookup table."""
    modality = get_modality(opt)
    zone = opt.zone_focus  # "Z2", "Z3", "Z4", or None
    
    # Try exact match first (for runs with zone)
    key = (modality, zone)
    if key in BASE_BENEFITS:
        return BASE_BENEFITS[key]
    
    # Fallback to modality-only
    key = (modality, None)
    if key in BASE_BENEFITS:
        return BASE_BENEFITS[key]
    
    # Ultimate fallback
    return 20.0


def compute_benefit(opt: WorkoutOption, ctx: ScoringContext) -> tuple[float, list[str]]:
    """Compute benefit for an option with applied rules.
    
    Returns:
        Tuple of (benefit_value, list_of_rule_codes)
    """
    benefit = _get_base_benefit(opt)
    rules: list[str] = []
    modality = get_modality(opt)
    
    # Z4 great-day bonus: recovery >= 85, no fatigue, no leg doms
    if opt.type == WorkoutType.RUN_Z4:
        if (
            ctx.recovery_score >= RECOVERY_HIGH_THRESHOLD
            and ctx.recent_heavy_count_3d == 0
            and not ctx.last_leg_doms_high
        ):
            benefit += BENEFIT_Z4_GREAT
            rules.append("z4_great")
    
    # DOMS boost: mobility/walk/upper get bonus when leg doms high
    if ctx.last_leg_doms_high:
        if modality in ("mobility", "walk"):
            benefit += BENEFIT_DOMS_BOOST
            rules.append("doms_boost")
    
    return benefit, rules


def compute_cost(opt: WorkoutOption, ctx: ScoringContext) -> tuple[float, list[str]]:
    """Compute cost for an option with applied rules.
    
    Returns:
        Tuple of (cost_value, list_of_rule_codes)
    """
    cost = 0.0
    rules: list[str] = []
    modality = get_modality(opt)
    
    # === Fatigue guardrail ===
    if ctx.recent_heavy_count_3d >= 2:
        # Hard options: Z4, heavy kettlebell
        if opt.type == WorkoutType.RUN_Z4 or opt.id == "kb_20":
            cost += COST_FATIGUE_HARD
            rules.append("fatigue_hard")
        # Medium-hard: Z3, normal strength
        elif opt.type == WorkoutType.RUN_Z3 or modality == "strength":
            cost += COST_FATIGUE_MED
            rules.append("fatigue_med")
    
    # === Anti-repeat modality ===
    if ctx.last_modality and modality == ctx.last_modality:
        cost += COST_REPEAT_MOD
        rules.append("repeat_mod")
    
    # 2-day repeat: if last two days same modality as this
    if ctx.last_two_modalities:
        m1, m2 = ctx.last_two_modalities
        if m1 == modality and m2 == modality:
            cost += COST_REPEAT_2D
            rules.append("repeat_2d")
    
    # === Leg DOMS penalty ===
    if ctx.last_leg_doms_high:
        # Heavy leg load: running Z3/Z4, heavy kb, leg-heavy options
        if opt.type in (WorkoutType.RUN_Z3, WorkoutType.RUN_Z4):
            cost += COST_LEGS_DOMS_HEAVY
            rules.append("legs_doms")
        elif opt.is_leg_heavy:
            cost += COST_LEGS_DOMS_HEAVY
            rules.append("legs_doms")
        elif opt.type == WorkoutType.BARRE:
            cost += COST_LEGS_DOMS_BARRE
            rules.append("legs_doms")
        elif opt.type == WorkoutType.RUN_Z2:
            # Even Z2 has impact on sore legs
            cost += COST_LEGS_DOMS_BARRE
            rules.append("legs_doms")
    
    # === Z4 "not default" ===
    if opt.type == WorkoutType.RUN_Z4:
        if ctx.recovery_score < RECOVERY_LOW_THRESHOLD:
            cost += COST_Z4_LOW_REC
            rules.append("z4_low_rec")
    
    return cost, rules


def score_options_v2(
    options: list[WorkoutOption],
    ctx: ScoringContext,
) -> list[ScoredOption]:
    """Score options using soft scoring context.
    
    Args:
        options: List of allowed workout options (post hard-constraint filtering)
        ctx: Soft scoring context with fatigue/history signals
        
    Returns:
        Sorted list of scored options (best first)
    """
    scored = []
    
    for opt in options:
        benefit, benefit_rules = compute_benefit(opt, ctx)
        cost, cost_rules = compute_cost(opt, ctx)
        net = benefit - cost
        
        all_rules = benefit_rules + cost_rules
        debug = ScoringDebug(
            benefit=benefit,
            cost=cost,
            net_score=net,
            rules=all_rules,
        )
        
        scored.append(ScoredOption(
            option=opt,
            benefit=benefit,
            cost=cost,
            net_score=net,
            debug=debug,
        ))
    
    # Sort by net score descending
    scored.sort(key=lambda x: x.net_score, reverse=True)
    
    # Assign ranks
    for i, s in enumerate(scored):
        s.rank = i + 1
    
    return scored


def score_options(
    options: list[WorkoutOption],
    recovery_score: int | None,
    yesterday_strain: float | None,
    soreness: int | None,
) -> list[ScoredOption]:
    """Score options by benefit/cost, return sorted list.
    
    Legacy API - wraps score_options_v2 with default context.
    The yesterday_strain parameter is kept for API compatibility but
    not currently used in v0.5 soft scoring rules.
    
    Args:
        options: List of allowed workout options
        recovery_score: WHOOP recovery 0-100
        yesterday_strain: Yesterday's strain (0-21 scale) - unused in v0.5
        soreness: Soreness level 0-3
        
    Returns:
        Sorted list of scored options (best first)
    """
    ctx = ScoringContext(
        recovery_score=recovery_score if recovery_score is not None else 50,
        soreness=soreness if soreness is not None else 0,
        # These are filled in by generator when using full context
        recent_heavy_count_3d=0,
        last_leg_doms_high=False,
        last_modality=None,
        last_two_modalities=None,
    )
    
    # Convert high soreness to leg doms flag for backward compatibility
    if ctx.soreness >= 3:
        ctx.last_leg_doms_high = True
    
    return score_options_v2(options, ctx)


def select_top_options(
    scored: list[ScoredOption],
    count: int = 3,
    ensure_variety: bool = True,
) -> list[ScoredOption]:
    """Select top N options, optionally ensuring variety.
    
    If ensure_variety=True, tries to include at least one run and one non-run option.
    
    Note: For v0.5+, prefer select_diversified_options() which uses modality-aware
    selection (primary + easy + different modality).
    """
    if len(scored) <= count:
        return scored
    
    if not ensure_variety:
        return scored[:count]
    
    # Find best run and best non-run
    best_run = next((s for s in scored if "run" in s.option.type.value), None)
    best_non_run = next((s for s in scored if "run" not in s.option.type.value), None)
    
    selected = []
    remaining = scored.copy()
    
    # Ensure at least one run if available
    if best_run and best_run not in selected:
        selected.append(best_run)
        remaining.remove(best_run)
    
    # Ensure at least one non-run if available
    if best_non_run and best_non_run not in selected:
        selected.append(best_non_run)
        remaining.remove(best_non_run)
    
    # Fill rest with top remaining
    for s in remaining:
        if len(selected) >= count:
            break
        if s not in selected:
            selected.append(s)
    
    # Re-sort by score
    selected.sort(key=lambda x: x.net_score, reverse=True)
    
    return selected


def select_diversified_options(
    scored: list[ScoredOption],
) -> list[ScoredOption]:
    """Select 2-3 diversified options using modality-aware logic.
    
    Selection strategy:
    1. Primary = best score overall
    2. Easy alternative = best from {mobility, walk, run_z2}, different option_id
    3. Different modality = best score with modality != primary
    
    Fallbacks if subsets are empty.
    
    Returns:
        List of 2-3 scored options
    """
    if len(scored) == 0:
        return []
    
    if len(scored) == 1:
        return scored
    
    selected: list[ScoredOption] = []
    used_ids: set[str] = set()
    
    # 1. Primary = best score
    primary = scored[0]
    selected.append(primary)
    used_ids.add(primary.option.id)
    primary_modality = get_modality(primary.option)
    
    # 2. Easy alternative from {mobility, walk, run_z2}
    easy_candidates = [
        s for s in scored
        if s.option.type in EASY_TYPES and s.option.id not in used_ids
    ]
    
    if easy_candidates:
        easy = easy_candidates[0]  # Already sorted by score
        selected.append(easy)
        used_ids.add(easy.option.id)
    
    # 3. Different modality from primary
    diff_modality_candidates = [
        s for s in scored
        if get_modality(s.option) != primary_modality and s.option.id not in used_ids
    ]
    
    if diff_modality_candidates:
        diff_mod = diff_modality_candidates[0]
        selected.append(diff_mod)
        used_ids.add(diff_mod.option.id)
    
    # Fallback: if we have < 2 options, fill with next best
    if len(selected) < 2:
        for s in scored:
            if s.option.id not in used_ids:
                selected.append(s)
                used_ids.add(s.option.id)
                if len(selected) >= 2:
                    break
    
    # Limit to 3 and re-sort by score
    selected = selected[:3]
    selected.sort(key=lambda x: x.net_score, reverse=True)
    
    return selected
