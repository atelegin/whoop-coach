"""Inline keyboards for Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from whoop_coach.db.models import EquipmentProfile

# Display names for equipment profiles
EQUIPMENT_LABELS = {
    EquipmentProfile.HOME_FULL: "🏠 Дом (гиря)",
    EquipmentProfile.TRAVEL_BANDS: "🎒 Ремни",
    EquipmentProfile.TRAVEL_NONE: "✋ Ничего",
}

# Short names for button text
EQUIPMENT_BUTTONS = {
    EquipmentProfile.HOME_FULL: "дом",
    EquipmentProfile.TRAVEL_BANDS: "ремни",
    EquipmentProfile.TRAVEL_NONE: "ничего",
}


def equipment_keyboard(current: EquipmentProfile) -> InlineKeyboardMarkup:
    """Build inline keyboard for equipment selection.

    Current selection is marked with ✓.
    """
    buttons = []
    for profile in EquipmentProfile:
        text = EQUIPMENT_BUTTONS[profile]
        if profile == current:
            text = f"✓ {text}"
        buttons.append(
            InlineKeyboardButton(
                text=text,
                callback_data=f"gear:{profile.value}",
            )
        )
    return InlineKeyboardMarkup([buttons])


def workout_candidates_keyboard(
    candidates: list, log_id: str
) -> InlineKeyboardMarkup:
    """Build keyboard for selecting from multiple workout candidates.

    Args:
        candidates: List of MatchCandidate objects
        log_id: PendingLog UUID as string
    """
    buttons = []
    for c in candidates[:5]:  # Limit to 5 candidates
        # Format: "HH:MM (30m) strain 12.5"
        time_str = c.end.strftime("%H:%M")
        text = f"{time_str} ({c.duration_min}м) strain {c.strain:.1f}"
        buttons.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"workout_select:{c.workout_id}:{log_id}",
            )
        ])
    return InlineKeyboardMarkup(buttons)


def rpe_keyboard(log_id: str) -> InlineKeyboardMarkup:
    """Build RPE 1-5 keyboard.

    Args:
        log_id: PendingLog UUID as string
    """
    labels = {1: "1 🟢", 2: "2", 3: "3 🟡", 4: "4", 5: "5 🔴"}
    buttons = [
        InlineKeyboardButton(
            text=labels[i],
            callback_data=f"rpe:{log_id}:{i}",
        )
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup([buttons])


def kb_weight_keyboard(log_id: str) -> InlineKeyboardMarkup:
    """Build kettlebell weight selection keyboard (12kg / 20kg).

    Args:
        log_id: PendingLog UUID as string
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="12 кг",
                callback_data=f"kb_weight:{log_id}:12",
            ),
            InlineKeyboardButton(
                text="20 кг",
                callback_data=f"kb_weight:{log_id}:20",
            ),
        ]
    ])


def retry_keyboard(log_id: str) -> InlineKeyboardMarkup:
    """Build retry button when no workout found.

    Args:
        log_id: PendingLog UUID as string
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="🔄 Повторить поиск",
                callback_data=f"retry:{log_id}",
            )
        ]
    ])


# === Stage 3: Smart Questions Keyboards ===

# Pain location options
PAIN_LOCATIONS = ["нет", "колено", "икры", "бедро", "поясница", "плечо"]


def soreness_keyboard(date_str: str) -> InlineKeyboardMarkup:
    """Build soreness 0-3 keyboard.

    Args:
        date_str: Date string (YYYY-MM-DD) for callback
    
    Callback format: soreness:{date}:{value}
    """
    labels = {0: "0 нет", 1: "1 чуть", 2: "2 заметно", 3: "3 сильно"}
    buttons = [
        InlineKeyboardButton(
            text=labels[i],
            callback_data=f"soreness:{date_str}:{i}",
        )
        for i in range(4)
    ]
    return InlineKeyboardMarkup([buttons])


def pain_locations_keyboard(
    date_str: str, selected: set[str] | None = None
) -> InlineKeyboardMarkup:
    """Build pain locations multi-select keyboard.

    Args:
        date_str: Date string (YYYY-MM-DD) for callback
        selected: Currently selected locations (empty by default)

    Callback format: pain:{date}:{location}
    Done button: pain_done:{date}
    
    Rule: if "нет" is selected, all other selections are cleared.
    """
    if selected is None:
        selected = set()
    
    buttons = []
    for loc in PAIN_LOCATIONS:
        text = f"✓ {loc}" if loc in selected else loc
        buttons.append(
            InlineKeyboardButton(
                text=text,
                callback_data=f"pain:{date_str}:{loc}",
            )
        )
    
    # Two rows: first 3, then 3, then done button
    keyboard = [
        buttons[:3],
        buttons[3:],
        [
            InlineKeyboardButton(
                text="✅ Готово",
                callback_data=f"pain_done:{date_str}",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def unattributed_rpe_keyboard(workout_id: str) -> InlineKeyboardMarkup:
    """Build RPE 1-5 keyboard for unattributed workout.

    Args:
        workout_id: WHOOP workout ID

    Callback format: unattr_rpe:{workout_id}:{value}
    """
    labels = {1: "1 🟢", 2: "2", 3: "3 🟡", 4: "4", 5: "5 🔴"}
    buttons = [
        InlineKeyboardButton(
            text=labels[i],
            callback_data=f"unattr_rpe:{workout_id}:{i}",
        )
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup([buttons])
