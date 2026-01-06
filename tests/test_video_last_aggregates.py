"""Tests for video_last aggregates and helpers."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from whoop_coach.db.models import (
    Base, Feedback, PendingLog, PendingLogState, User, Video, EquipmentProfile
)
from whoop_coach.videos.service import (
    format_session_metrics,
    profile_key,
    rpe_mean_to_words,
    escape_html,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestHelpers:
    """Tests for helper functions."""

    def test_profile_key_normal(self):
        """Profile key with both values."""
        assert profile_key(20, 12) == "H20-S12"
        assert profile_key(12, 20) == "H12-S20"

    def test_profile_key_with_none(self):
        """Profile key with None values shows ?."""
        assert profile_key(None, 12) == "H?-S12"
        assert profile_key(20, None) == "H20-S?"
        assert profile_key(None, None) == "H?-S?"

    def test_rpe_mean_to_words_ranges(self):
        """RPE mean correctly maps to Variant C masculine words."""
        assert rpe_mean_to_words(1.0) == "Сделал разминку"
        assert rpe_mean_to_words(1.4) == "Сделал разминку"
        assert rpe_mean_to_words(2.0) == "Мог бы сделать ещё одну"
        assert rpe_mean_to_words(2.4) == "Мог бы сделать ещё одну"
        assert rpe_mean_to_words(3.0) == "Хватит на сегодня"
        assert rpe_mean_to_words(3.4) == "Хватит на сегодня"
        assert rpe_mean_to_words(4.0) == "Еле дожал"
        assert rpe_mean_to_words(4.4) == "Еле дожал"
        assert rpe_mean_to_words(5.0) == "Меня вынесло"

    def test_escape_html_basic(self):
        """Escape HTML special chars."""
        assert escape_html("<script>") == "&lt;script&gt;"
        assert escape_html("Tom & Jerry") == "Tom &amp; Jerry"
        assert escape_html('Say "hello"') == "Say &quot;hello&quot;"
        assert escape_html("It's fine") == "It&#39;s fine"

    def test_escape_html_combined(self):
        """Escape multiple special chars."""
        text = '<b>"Test" & \'more\'</b>'
        expected = "&lt;b&gt;&quot;Test&quot; &amp; &#39;more&#39;&lt;/b&gt;"
        assert escape_html(text) == expected


class TestFormatSessionMetrics:
    """Tests for format_session_metrics."""

    def test_shows_metrics_when_present(self, db_session: Session):
        """Session metrics shown when WHOOP snapshot present."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        log = PendingLog(
            user_id=user.id,
            video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.MATCHED,
            whoop_workout_id="w123",
            whoop_workout_type="Strength Training",
            whoop_strain=10.5,
            whoop_duration_s=1800,
            whoop_hr_avg=145,
            whoop_hr_max=172,
            matched_at=now,
        )
        db_session.add(log)
        db_session.commit()

        result = format_session_metrics(log)
        assert "strain 10.5" in result
        assert "30 мин" in result
        assert "HR 145/172" in result
        assert "Strength Training" in result

    def test_matched_but_no_metrics(self, db_session: Session):
        """Shows 'смэтчилось, но метрик нет' when match exists but no metrics."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        log = PendingLog(
            user_id=user.id,
            video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.MATCHED,
            whoop_workout_id="w123",  # Match happened but no metrics
            matched_at=now,
        )
        db_session.add(log)
        db_session.commit()

        result = format_session_metrics(log)
        assert "смэтчилось, но метрик нет" in result

    def test_not_matched_shows_retry(self, db_session: Session):
        """Shows '/retry' when no match."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        log = PendingLog(
            user_id=user.id,
            video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
            # No whoop_workout_id, no matched_at
        )
        db_session.add(log)
        db_session.commit()

        result = format_session_metrics(log)
        assert "не смэтчилось" in result
        assert "/retry" in result


class TestProfileAggregates:
    """Tests for profile-based aggregates."""

    def test_strain_grouped_by_profile(self, db_session: Session):
        """Strain aggregates correctly grouped by KB profile."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=3, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        # Two logs with H12-S12, strain 8 and 10 -> avg 9
        log1 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=12, kb_swing_kg_at_time=12,
            whoop_strain=8.0, whoop_workout_id="w1", matched_at=now,
        )
        log2 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=12, kb_swing_kg_at_time=12,
            whoop_strain=10.0, whoop_workout_id="w2", matched_at=now,
        )
        # One log with H20-S12, strain 12 -> avg 12
        log3 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=20, kb_swing_kg_at_time=12,
            whoop_strain=12.0, whoop_workout_id="w3", matched_at=now,
        )
        db_session.add_all([log1, log2, log3])
        db_session.commit()

        # Use sync query to verify aggregates logic
        from sqlalchemy import func, select

        stmt = (
            select(
                PendingLog.kb_heavy_kg_at_time,
                PendingLog.kb_swing_kg_at_time,
                func.avg(PendingLog.whoop_strain),
                func.count(),
            )
            .where(
                PendingLog.user_id == user.id,
                PendingLog.video_id == "test123456",
                PendingLog.whoop_strain.isnot(None),
                PendingLog.kb_heavy_kg_at_time.isnot(None),
                PendingLog.kb_swing_kg_at_time.isnot(None),
            )
            .group_by(PendingLog.kb_heavy_kg_at_time, PendingLog.kb_swing_kg_at_time)
            .order_by(func.count().desc())
        )
        result = db_session.execute(stmt).all()

        assert len(result) == 2
        # H12-S12 has 2 entries (most frequent) - avg 9
        profile_12_12 = [r for r in result if r[0] == 12 and r[1] == 12][0]
        assert profile_12_12[2] == 9.0  # avg strain
        assert profile_12_12[3] == 2    # count
        # H20-S12 has 1 entry - avg 12
        profile_20_12 = [r for r in result if r[0] == 20 and r[1] == 12][0]
        assert profile_20_12[2] == 12.0
        assert profile_20_12[3] == 1

    def test_effort_grouped_by_profile(self, db_session: Session):
        """Effort (RPE) aggregates correctly grouped by KB profile."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=3, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        # Create logs with linked feedback
        log1 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=12, kb_swing_kg_at_time=12,
            whoop_workout_id="w1", matched_at=now,
        )
        log2 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=12, kb_swing_kg_at_time=12,
            whoop_workout_id="w2", matched_at=now,
        )
        log3 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=20, kb_swing_kg_at_time=12,
            whoop_workout_id="w3", matched_at=now,
        )
        db_session.add_all([log1, log2, log3])
        db_session.commit()

        # Add feedback linked to logs
        fb1 = Feedback(user_id=user.id, pending_log_id=log1.id, rpe_1_5=3)
        fb2 = Feedback(user_id=user.id, pending_log_id=log2.id, rpe_1_5=4)
        fb3 = Feedback(user_id=user.id, pending_log_id=log3.id, rpe_1_5=2)
        db_session.add_all([fb1, fb2, fb3])
        db_session.commit()

        from sqlalchemy import func, select

        stmt = (
            select(
                PendingLog.kb_heavy_kg_at_time,
                PendingLog.kb_swing_kg_at_time,
                func.avg(Feedback.rpe_1_5),
                func.count(),
            )
            .join(Feedback, Feedback.pending_log_id == PendingLog.id)
            .where(
                PendingLog.user_id == user.id,
                PendingLog.video_id == "test123456",
                Feedback.rpe_1_5.isnot(None),
                PendingLog.kb_heavy_kg_at_time.isnot(None),
                PendingLog.kb_swing_kg_at_time.isnot(None),
            )
            .group_by(PendingLog.kb_heavy_kg_at_time, PendingLog.kb_swing_kg_at_time)
            .order_by(func.count().desc())
        )
        result = db_session.execute(stmt).all()

        assert len(result) == 2
        # H12-S12: avg of 3 and 4 = 3.5
        profile_12_12 = [r for r in result if r[0] == 12 and r[1] == 12][0]
        assert profile_12_12[2] == 3.5
        assert profile_12_12[3] == 2
        # H20-S12: avg of 2 = 2.0
        profile_20_12 = [r for r in result if r[0] == 20 and r[1] == 12][0]
        assert profile_20_12[2] == 2.0
        assert profile_20_12[3] == 1

    def test_excludes_null_profile_rows(self, db_session: Session):
        """Rows with NULL kb weights are excluded from grouped aggregates."""
        user = User(telegram_id=123)
        db_session.add(user)
        db_session.commit()

        now = datetime.now(timezone.utc)
        video = Video(video_id="test123456", usage_count=2, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()

        # Log with proper profile
        log1 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=20, kb_swing_kg_at_time=12,
            whoop_strain=10.0, whoop_workout_id="w1", matched_at=now,
        )
        # Log with NULL heavy_kg - should be excluded
        log2 = PendingLog(
            user_id=user.id, video_id="test123456",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now, state=PendingLogState.CONFIRMED,
            kb_heavy_kg_at_time=None, kb_swing_kg_at_time=12,
            whoop_strain=15.0, whoop_workout_id="w2", matched_at=now,
        )
        db_session.add_all([log1, log2])
        db_session.commit()

        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .where(
                PendingLog.user_id == user.id,
                PendingLog.video_id == "test123456",
                PendingLog.whoop_strain.isnot(None),
                PendingLog.kb_heavy_kg_at_time.isnot(None),
                PendingLog.kb_swing_kg_at_time.isnot(None),
            )
        )
        result = db_session.execute(stmt).scalar()

        # Only 1 row should match (log1), log2 is excluded
        assert result == 1
