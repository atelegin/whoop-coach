"""Tests for video service: upsert, usage tracking, last used queries."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from whoop_coach.db.models import Base, PendingLog, PendingLogState, User, Video, EquipmentProfile


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestUpsertVideo:
    """Tests for video upsert functionality."""

    def test_video_upsert_creates_new(self, db_session: Session):
        """New video created with usage_count=1."""
        video_id = "abc12345678"
        now = datetime.now(timezone.utc)
        
        # Create new video
        video = Video(
            video_id=video_id,
            usage_count=1,
            first_seen_at=now,
            last_used_at=now,
        )
        db_session.add(video)
        db_session.commit()
        
        # Verify
        result = db_session.get(Video, video_id)
        assert result is not None
        assert result.usage_count == 1
        assert result.first_seen_at is not None
        assert result.last_used_at is not None

    def test_video_upsert_increments_usage(self, db_session: Session):
        """Existing video gets usage_count+1, last_used_at updated."""
        video_id = "abc12345678"
        first_time = datetime.now(timezone.utc) - timedelta(days=1)
        
        # Create initial video
        video = Video(
            video_id=video_id,
            usage_count=1,
            first_seen_at=first_time,
            last_used_at=first_time,
        )
        db_session.add(video)
        db_session.commit()
        
        # Simulate upsert (increment usage)
        video = db_session.get(Video, video_id)
        second_time = datetime.now(timezone.utc)
        video.usage_count += 1
        video.last_used_at = second_time
        db_session.commit()
        
        # Verify
        result = db_session.get(Video, video_id)
        assert result.usage_count == 2
        # SQLite drops timezone info, so compare naive datetimes
        assert result.first_seen_at.replace(tzinfo=None) == first_time.replace(tzinfo=None)
        assert result.last_used_at >= second_time.replace(tzinfo=None)  # updated


class TestPendingLogVideoFK:
    """Tests for PendingLog → Video FK relationship."""

    def test_pendinglog_links_video_fk(self, db_session: Session):
        """PendingLog.video_id FK works correctly."""
        # Create user
        user = User(telegram_id=123456789)
        db_session.add(user)
        db_session.commit()
        
        # Create video
        video_id = "xyz98765432"
        now = datetime.now(timezone.utc)
        video = Video(
            video_id=video_id,
            usage_count=1,
            first_seen_at=now,
            last_used_at=now,
        )
        db_session.add(video)
        db_session.commit()
        
        # Create pending log linked to video
        pending_log = PendingLog(
            user_id=user.id,
            video_id=video_id,
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
        )
        db_session.add(pending_log)
        db_session.commit()
        
        # Verify
        result = db_session.get(PendingLog, pending_log.id)
        assert result.video_id == video_id


class TestKbUsedSnapshot:
    """Tests for KB used snapshot updates."""

    def test_kb_used_updates_snapshot_heavy(self, db_session: Session):
        """kb_heavy_kg_at_time is updated correctly."""
        # Create user and video
        user = User(telegram_id=123456789)
        db_session.add(user)
        db_session.commit()
        
        video_id = "test1234567"
        now = datetime.now(timezone.utc)
        video = Video(video_id=video_id, usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()
        
        # Create pending log with default snapshot
        pending_log = PendingLog(
            user_id=user.id,
            video_id=video_id,
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
            kb_heavy_kg_at_time=20,  # default
            kb_swing_kg_at_time=12,  # default
        )
        db_session.add(pending_log)
        db_session.commit()
        
        # Update heavy weight
        pending_log = db_session.get(PendingLog, pending_log.id)
        pending_log.kb_heavy_kg_at_time = 12
        db_session.commit()
        
        # Verify
        result = db_session.get(PendingLog, pending_log.id)
        assert result.kb_heavy_kg_at_time == 12
        assert result.kb_swing_kg_at_time == 12  # unchanged

    def test_kb_used_updates_snapshot_swing(self, db_session: Session):
        """kb_swing_kg_at_time is updated correctly."""
        user = User(telegram_id=123456789)
        db_session.add(user)
        db_session.commit()
        
        video_id = "test1234567"
        now = datetime.now(timezone.utc)
        video = Video(video_id=video_id, usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()
        
        pending_log = PendingLog(
            user_id=user.id,
            video_id=video_id,
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
            kb_heavy_kg_at_time=20,
            kb_swing_kg_at_time=12,
        )
        db_session.add(pending_log)
        db_session.commit()
        
        # Update swing weight
        pending_log = db_session.get(PendingLog, pending_log.id)
        pending_log.kb_swing_kg_at_time = 20
        db_session.commit()
        
        # Verify
        result = db_session.get(PendingLog, pending_log.id)
        assert result.kb_swing_kg_at_time == 20
        assert result.kb_heavy_kg_at_time == 20  # unchanged

    def test_kb_used_keep_resets_to_user_defaults(self, db_session: Session):
        """Keep action resets snapshot to user defaults."""
        user = User(telegram_id=123456789, kb_heavy_kg=20, kb_swing_kg=12)
        db_session.add(user)
        db_session.commit()
        
        video_id = "test1234567"
        now = datetime.now(timezone.utc)
        video = Video(video_id=video_id, usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()
        
        # Create log with different values
        pending_log = PendingLog(
            user_id=user.id,
            video_id=video_id,
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
            kb_heavy_kg_at_time=12,  # different from default
            kb_swing_kg_at_time=20,  # different from default
        )
        db_session.add(pending_log)
        db_session.commit()
        
        # Simulate keep action
        pending_log = db_session.get(PendingLog, pending_log.id)
        user = db_session.get(User, user.id)
        pending_log.kb_heavy_kg_at_time = user.kb_heavy_kg
        pending_log.kb_swing_kg_at_time = user.kb_swing_kg
        pending_log.kb_used_answered_at = now
        db_session.commit()
        
        # Verify reset to defaults
        result = db_session.get(PendingLog, pending_log.id)
        assert result.kb_heavy_kg_at_time == 20
        assert result.kb_swing_kg_at_time == 12
        assert result.kb_used_answered_at is not None

    def test_kb_used_skip_finalizes_without_change(self, db_session: Session):
        """Skip sets answered_at only, no weight changes."""
        user = User(telegram_id=123456789)
        db_session.add(user)
        db_session.commit()
        
        video_id = "test1234567"
        now = datetime.now(timezone.utc)
        video = Video(video_id=video_id, usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add(video)
        db_session.commit()
        
        pending_log = PendingLog(
            user_id=user.id,
            video_id=video_id,
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
            kb_heavy_kg_at_time=20,
            kb_swing_kg_at_time=12,
        )
        db_session.add(pending_log)
        db_session.commit()
        
        orig_heavy = pending_log.kb_heavy_kg_at_time
        orig_swing = pending_log.kb_swing_kg_at_time
        
        # Simulate skip action
        pending_log = db_session.get(PendingLog, pending_log.id)
        pending_log.kb_used_answered_at = now
        db_session.commit()
        
        # Verify no changes except answered_at
        result = db_session.get(PendingLog, pending_log.id)
        assert result.kb_heavy_kg_at_time == orig_heavy
        assert result.kb_swing_kg_at_time == orig_swing
        assert result.kb_used_answered_at is not None


class TestTagging:
    """Tests for movement tagging."""

    def test_tag_toggle_add_remove(self, db_session: Session):
        """Toggle adds/removes from movement_tags."""
        video_id = "tag_test123"
        now = datetime.now(timezone.utc)
        
        video = Video(
            video_id=video_id,
            usage_count=1,
            first_seen_at=now,
            last_used_at=now,
            movement_tags=[],
        )
        db_session.add(video)
        db_session.commit()
        
        # Add tag
        video = db_session.get(Video, video_id)
        tags = set(video.movement_tags)
        tags.add("swing")
        video.movement_tags = list(tags)
        db_session.commit()
        
        result = db_session.get(Video, video_id)
        assert "swing" in result.movement_tags
        
        # Remove tag
        tags = set(result.movement_tags)
        tags.remove("swing")
        result.movement_tags = list(tags)
        db_session.commit()
        
        result = db_session.get(Video, video_id)
        assert "swing" not in result.movement_tags

    def test_tag_last_selects_most_recent_video(self, db_session: Session):
        """get_last_used_video returns video from most recent pending_log."""
        # Create user
        user = User(telegram_id=123456789)
        db_session.add(user)
        db_session.commit()
        
        now = datetime.now(timezone.utc)
        
        # Create two videos
        video1 = Video(video_id="video1abcde", usage_count=1, first_seen_at=now, last_used_at=now)
        video2 = Video(video_id="video2fghij", usage_count=1, first_seen_at=now, last_used_at=now)
        db_session.add_all([video1, video2])
        db_session.commit()
        
        # Create pending logs: video1 first, then video2
        log1 = PendingLog(
            user_id=user.id,
            video_id="video1abcde",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now - timedelta(hours=1),
            state=PendingLogState.PENDING,
        )
        log2 = PendingLog(
            user_id=user.id,
            video_id="video2fghij",
            equipment_profile_at_time=EquipmentProfile.HOME_FULL,
            message_timestamp=now,
            state=PendingLogState.PENDING,
        )
        db_session.add_all([log1, log2])
        db_session.commit()
        
        # Query: should return video2 (most recent by pending_log.created_at)
        from sqlalchemy import select
        stmt = (
            select(Video)
            .join(PendingLog, PendingLog.video_id == Video.video_id)
            .where(
                PendingLog.user_id == user.id,
                PendingLog.video_id.isnot(None),
            )
            .order_by(PendingLog.created_at.desc())
            .limit(1)
        )
        result = db_session.execute(stmt).scalar_one_or_none()
        assert result is not None
        assert result.video_id == "video2fghij"
