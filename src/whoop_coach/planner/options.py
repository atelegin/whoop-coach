"""Workout options catalog.

Defines all available training options with their properties.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkoutType(str, Enum):
    """Type of workout."""
    
    RUN_Z2 = "run_z2"
    RUN_Z3 = "run_z3"
    RUN_Z4 = "run_z4"
    KETTLEBELL = "kettlebell"
    BANDS = "bands"
    BODYWEIGHT = "bodyweight"
    BARRE = "barre"
    MOBILITY = "mobility"
    WALKING = "walking"


class EquipmentRequired(str, Enum):
    """Equipment required for the workout."""
    
    NONE = "none"
    KETTLEBELL = "kettlebell"
    BANDS = "bands"


class ImpactLevel(str, Enum):
    """Impact level of the workout."""
    
    HIGH = "high"  # Running, jumping
    MEDIUM = "medium"  # Kettlebell swings
    LOW = "low"  # Barre, mobility, walking


@dataclass
class WorkoutOption:
    """A training option that can be recommended."""
    
    id: str
    name_ru: str
    type: WorkoutType
    zone_focus: str | None  # Z2, Z3, Z4, or None
    equipment_required: EquipmentRequired
    impact_level: ImpactLevel
    base_benefit: float  # 0-10 scale
    base_cost: float  # 0-10 scale, recovery impact
    duration_min: int  # Typical duration in minutes
    is_leg_heavy: bool = False  # Heavy leg load


# === Workout Options Catalog ===

ALL_OPTIONS: list[WorkoutOption] = [
    # Running
    WorkoutOption(
        id="run_z3_30",
        name_ru="🏃 Бег Z3, 30 мин",
        type=WorkoutType.RUN_Z3,
        zone_focus="Z3",
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.HIGH,
        base_benefit=7.0,
        base_cost=5.0,
        duration_min=30,
        is_leg_heavy=True,
    ),
    WorkoutOption(
        id="run_z3_45",
        name_ru="🏃 Бег Z3, 45 мин",
        type=WorkoutType.RUN_Z3,
        zone_focus="Z3",
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.HIGH,
        base_benefit=8.0,
        base_cost=6.5,
        duration_min=45,
        is_leg_heavy=True,
    ),
    WorkoutOption(
        id="run_z4_20",
        name_ru="🏃 Бег Z4 (качество), 20 мин",
        type=WorkoutType.RUN_Z4,
        zone_focus="Z4",
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.HIGH,
        base_benefit=9.0,
        base_cost=8.0,
        duration_min=20,
        is_leg_heavy=True,
    ),
    WorkoutOption(
        id="run_z2_30",
        name_ru="🚶‍♂️ Бег Z2 (run-walk), 30 мин",
        type=WorkoutType.RUN_Z2,
        zone_focus="Z2",
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.HIGH,
        base_benefit=5.0,
        base_cost=3.0,
        duration_min=30,
        is_leg_heavy=True,
    ),
    
    # Kettlebell
    WorkoutOption(
        id="kb_12",
        name_ru="🏋️ Гиря 12 кг",
        type=WorkoutType.KETTLEBELL,
        zone_focus=None,
        equipment_required=EquipmentRequired.KETTLEBELL,
        impact_level=ImpactLevel.MEDIUM,
        base_benefit=6.0,
        base_cost=4.0,
        duration_min=30,
        is_leg_heavy=False,
    ),
    WorkoutOption(
        id="kb_20",
        name_ru="🏋️ Гиря 20 кг",
        type=WorkoutType.KETTLEBELL,
        zone_focus=None,
        equipment_required=EquipmentRequired.KETTLEBELL,
        impact_level=ImpactLevel.MEDIUM,
        base_benefit=7.5,
        base_cost=6.0,
        duration_min=30,
        is_leg_heavy=True,  # Heavy kb is leg-intensive
    ),
    
    # Bands
    WorkoutOption(
        id="bands_strength",
        name_ru="💪 Силовая с ремнями",
        type=WorkoutType.BANDS,
        zone_focus=None,
        equipment_required=EquipmentRequired.BANDS,
        impact_level=ImpactLevel.LOW,
        base_benefit=5.5,
        base_cost=3.5,
        duration_min=30,
        is_leg_heavy=False,
    ),
    
    # Bodyweight
    WorkoutOption(
        id="bodyweight_strength",
        name_ru="💪 Силовая без инвентаря",
        type=WorkoutType.BODYWEIGHT,
        zone_focus=None,
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.LOW,
        base_benefit=5.0,
        base_cost=3.0,
        duration_min=30,
        is_leg_heavy=False,
    ),
    
    # Barre / Low-impact cardio
    WorkoutOption(
        id="barre",
        name_ru="🩰 Барре",
        type=WorkoutType.BARRE,
        zone_focus=None,
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.LOW,
        base_benefit=5.0,
        base_cost=2.5,
        duration_min=45,
        is_leg_heavy=False,
    ),
    
    # Mobility / Recovery
    WorkoutOption(
        id="mobility",
        name_ru="🧘 Мобилити / растяжка",
        type=WorkoutType.MOBILITY,
        zone_focus=None,
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.LOW,
        base_benefit=3.0,
        base_cost=0.5,
        duration_min=30,
        is_leg_heavy=False,
    ),
    
    # Walking
    WorkoutOption(
        id="walking",
        name_ru="🚶 Прогулка",
        type=WorkoutType.WALKING,
        zone_focus=None,
        equipment_required=EquipmentRequired.NONE,
        impact_level=ImpactLevel.LOW,
        base_benefit=2.0,
        base_cost=0.5,
        duration_min=30,
        is_leg_heavy=False,
    ),
]


def get_option_by_id(option_id: str) -> WorkoutOption | None:
    """Get workout option by ID."""
    for opt in ALL_OPTIONS:
        if opt.id == option_id:
            return opt
    return None
