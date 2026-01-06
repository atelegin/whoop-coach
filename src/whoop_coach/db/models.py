"""SQLAlchemy models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class EquipmentProfile(str, enum.Enum):
    """User's available equipment."""

    HOME_FULL = "home_full"  # Kettlebell available (12kg, 20kg)
    TRAVEL_BANDS = "travel_bands"  # Resistance bands only
    TRAVEL_NONE = "travel_none"  # Bodyweight only


class PendingLogState(str, enum.Enum):
    """State machine for pending logs.

    PENDING   — workout not found or not selected yet
    MATCHED   — workout selected (auto/manual), waiting for RPE
    CONFIRMED — RPE received, log closed
    CANCELLED — cancelled via /undo
    """

    PENDING = "pending"
    MATCHED = "matched"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User model — links Telegram ↔ WHOOP."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )
    whoop_user_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )
    whoop_tokens_enc: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    equipment_profile: Mapped[EquipmentProfile] = mapped_column(
        Enum(EquipmentProfile),
        default=EquipmentProfile.HOME_FULL,
        nullable=False,
    )
    hrmax_override: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # Kettlebell capabilities
    kb_overhead_max_kg: Mapped[int] = mapped_column(
        Integer,
        default=12,
        nullable=False,
    )
    kb_heavy_kg: Mapped[int] = mapped_column(
        Integer,
        default=20,
        nullable=False,
    )
    kb_swing_kg: Mapped[int] = mapped_column(
        Integer,
        default=12,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id}>"


class OAuthState(Base):
    """OAuth state for CSRF protection."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Video(Base):
    """YouTube video metadata."""

    __tablename__ = "videos"

    video_id: Mapped[str] = mapped_column(
        String(16),
        primary_key=True,
    )
    channel_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    language: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
    )
    # JSON works on both Postgres and SQLite
    tags: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    # Movement tags for KB weight assignment (e.g. ["overhead", "swing", "pull"])
    movement_tags: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PendingLog(Base):
    """Pending workout log awaiting match/confirmation.

    Note on /undo: when cancelling, only delete Feedback linked via
    pending_log_id to avoid removing manual feedback from other sources.
    """

    __tablename__ = "pending_logs"
    __table_args__ = (
        Index("ix_pending_logs_user_created", "user_id", "created_at"),
        Index("ix_pending_logs_user_state", "user_id", "state"),
        CheckConstraint("kb_weight_kg IN (12, 20)", name="ck_pending_logs_kb_weight"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("videos.video_id", ondelete="SET NULL"),
        nullable=True,
    )
    kb_weight_kg: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    equipment_profile_at_time: Mapped[EquipmentProfile] = mapped_column(
        Enum(EquipmentProfile),
        nullable=False,
    )
    # UTC-aware timestamp from update.message.date
    message_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    matched_workout_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    state: Mapped[PendingLogState] = mapped_column(
        Enum(PendingLogState),
        default=PendingLogState.PENDING,
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    # KB capability snapshots at log time
    kb_overhead_max_kg_at_time: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    kb_heavy_kg_at_time: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    kb_swing_kg_at_time: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Feedback(Base):
    """User feedback for a workout or morning check-in.
    
    For workout feedback: whoop_workout_id and/or pending_log_id set.
    For morning prompt: is_morning_prompt=True, feedback_date set.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_user_created", "user_id", "created_at"),
        CheckConstraint("rpe_1_5 BETWEEN 1 AND 5", name="ck_feedback_rpe"),
        CheckConstraint("soreness_0_3 BETWEEN 0 AND 3", name="ck_feedback_soreness"),
        UniqueConstraint(
            "user_id", "feedback_date", "is_morning_prompt",
            name="uq_feedback_user_date_morning",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    pending_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pending_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    whoop_workout_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    rpe_1_5: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # Stage 3: morning soreness/pain feedback
    soreness_0_3: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pain_locations: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    feedback_date: Mapped[datetime | None] = mapped_column(
        Date,
        nullable=True,
    )
    is_morning_prompt: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class WebhookEventStatus(str, enum.Enum):
    """Status of webhook event processing."""

    PENDING = "pending"
    PROCESSING = "processing"
    PENDING_SCORE = "pending_score"  # Recovery not scored yet
    AWAITING_FEEDBACK = "awaiting_feedback"  # Waiting for morning feedback
    DONE = "done"
    FAILED = "failed"


class WebhookEvent(Base):
    """WHOOP webhook event for idempotency and async processing."""

    __tablename__ = "whoop_webhook_events"
    __table_args__ = (
        Index("ix_webhook_events_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    trace_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    sleep_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    status: Mapped[WebhookEventStatus] = mapped_column(
        Enum(WebhookEventStatus),
        default=WebhookEventStatus.PENDING,
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class DailyPlan(Base):
    """User's training plan for a day."""

    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_date", name="uq_daily_plan_user_date"),
        Index("ix_daily_plans_user_date", "user_id", "plan_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
    )
    sleep_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    cycle_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    recovery_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    timezone_offset: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
    )
    options_shown: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    scoring_debug: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    selected_option_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    plan_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
