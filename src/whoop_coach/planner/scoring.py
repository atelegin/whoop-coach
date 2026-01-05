"""Soft scoring for workout options.

Implements spec section 11: benefit/cost optimization.
"""

from __future__ import annotations

from dataclasses import dataclass

from whoop_coach.planner.options import WorkoutOption, WorkoutType


@dataclass
class ScoredOption:
    """Workout option with computed scores."""
    
    option: WorkoutOption
    benefit: float
    cost: float
    net_score: float
    rank: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.option.id,
            "name_ru": self.option.name_ru,
            "benefit": round(self.benefit, 2),
            "cost": round(self.cost, 2),
            "net_score": round(self.net_score, 2),
            "rank": self.rank,
        }


def score_options(
    options: list[WorkoutOption],
    recovery_score: int | None,
    yesterday_strain: float | None,
    soreness: int | None,
) -> list[ScoredOption]:
    """Score options by benefit/cost, return sorted list.
    
    MVP scoring rules:
    - Benefit = base_benefit × recovery_multiplier
    - Cost = base_cost × (1 + soreness/3) × strain_multiplier
    - Net = benefit - cost
    
    Args:
        options: List of allowed workout options
        recovery_score: WHOOP recovery 0-100
        yesterday_strain: Yesterday's strain (0-21 scale)
        soreness: Soreness level 0-3
        
    Returns:
        Sorted list of scored options (best first)
    """
    recovery = recovery_score if recovery_score is not None else 50
    soreness = soreness if soreness is not None else 0
    strain = yesterday_strain if yesterday_strain is not None else 10.0
    
    # Recovery multiplier: high recovery = can do more intense
    # 0-33: low (0.6-0.8), 34-66: medium (0.8-1.0), 67-100: high (1.0-1.2)
    if recovery >= 67:
        recovery_mult = 1.0 + (recovery - 67) / 100  # 1.0-1.33
    elif recovery >= 33:
        recovery_mult = 0.8 + (recovery - 33) / 170  # 0.8-1.0
    else:
        recovery_mult = 0.6 + recovery / 110  # 0.6-0.9
    
    # Strain multiplier for cost: high strain yesterday = higher cost today
    strain_mult = 1.0 + max(0, strain - 14) / 20  # 1.0 if <14, up to 1.35 at 21
    
    # Soreness multiplier for cost
    soreness_mult = 1.0 + soreness / 3  # 1.0-2.0
    
    scored = []
    for opt in options:
        benefit = opt.base_benefit * recovery_mult
        cost = opt.base_cost * soreness_mult * strain_mult
        
        # Bonus for Z3 (default base run)
        if opt.type == WorkoutType.RUN_Z3:
            benefit *= 1.1
        
        # Penalty for high-impact when recovery is low
        if recovery < 33 and opt.impact_level.value == "high":
            cost *= 1.3
        
        net = benefit - cost
        scored.append(ScoredOption(option=opt, benefit=benefit, cost=cost, net_score=net))
    
    # Sort by net score descending
    scored.sort(key=lambda x: x.net_score, reverse=True)
    
    # Assign ranks
    for i, s in enumerate(scored):
        s.rank = i + 1
    
    return scored


def select_top_options(
    scored: list[ScoredOption],
    count: int = 3,
    ensure_variety: bool = True,
) -> list[ScoredOption]:
    """Select top N options, optionally ensuring variety.
    
    If ensure_variety=True, tries to include at least one run and one non-run option.
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
