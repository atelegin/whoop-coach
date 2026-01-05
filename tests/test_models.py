"""Test database models."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from whoop_coach.db.models import Base, EquipmentProfile, User


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_user(db_session: Session):
    """Test creating a user."""
    user = User(telegram_id=123456789)
    db_session.add(user)
    db_session.commit()

    result = db_session.execute(select(User)).scalar_one()
    assert result.telegram_id == 123456789
    assert result.equipment_profile == EquipmentProfile.HOME_FULL
    assert result.whoop_user_id is None
    assert result.whoop_tokens_enc is None
    assert result.id is not None
    assert result.created_at is not None


def test_equipment_profile_values():
    """Test equipment profile enum values."""
    assert EquipmentProfile.HOME_FULL.value == "home_full"
    assert EquipmentProfile.TRAVEL_BANDS.value == "travel_bands"
    assert EquipmentProfile.TRAVEL_NONE.value == "travel_none"


def test_update_equipment_profile(db_session: Session):
    """Test updating user equipment profile."""
    user = User(telegram_id=123456789)
    db_session.add(user)
    db_session.commit()

    user.equipment_profile = EquipmentProfile.TRAVEL_BANDS
    db_session.commit()

    result = db_session.execute(select(User)).scalar_one()
    assert result.equipment_profile == EquipmentProfile.TRAVEL_BANDS
