"""KB weight assignment logic.

Assigns kettlebell weights based on video movement tags and user capabilities.
"""

from dataclasses import dataclass


@dataclass
class UserKbCaps:
    """User's kettlebell capabilities."""
    
    kb_overhead_max_kg: int = 12
    kb_heavy_kg: int = 20
    kb_swing_kg: int = 12


# Movement tags that use heavy weight
HEAVY_TAGS = {"pull", "squat", "carry"}


def assign_kb_weights(movement_tags: list[str], user_kb: UserKbCaps) -> dict[str, int]:
    """Assign KB weights based on movement tags and user capabilities.
    
    Rules:
    - overhead → user.kb_overhead_max_kg (default 12)
    - swing → user.kb_swing_kg (12 or 20)
    - pull/squat/carry → user.kb_heavy_kg (default 20)
    
    Args:
        movement_tags: List of movement pattern tags from video
        user_kb: User's KB capability settings
        
    Returns:
        Dict with keys: overhead_kg, swing_kg, heavy_kg (only present if tag matches)
    """
    if not movement_tags:
        return {}
    
    tags_set = set(t.lower() for t in movement_tags)
    weights: dict[str, int] = {}
    
    if "overhead" in tags_set:
        weights["overhead_kg"] = user_kb.kb_overhead_max_kg
    
    if "swing" in tags_set:
        weights["swing_kg"] = user_kb.kb_swing_kg
    
    if tags_set & HEAVY_TAGS:
        weights["heavy_kg"] = user_kb.kb_heavy_kg
    
    return weights


def format_kb_weights_ru(weights: dict[str, int]) -> str:
    """Format weights as compact Russian string.
    
    Example: "над головой 12 кг; свинг 20 кг; тяга/присед/переноски 20 кг"
    
    Args:
        weights: Dict from assign_kb_weights
        
    Returns:
        Formatted string, empty if no weights
    """
    parts = []
    
    if "overhead_kg" in weights:
        parts.append(f"над головой {weights['overhead_kg']} кг")
    
    if "swing_kg" in weights:
        parts.append(f"свинг {weights['swing_kg']} кг")
    
    if "heavy_kg" in weights:
        parts.append(f"тяга/присед/переноски {weights['heavy_kg']} кг")
    
    return "; ".join(parts)
