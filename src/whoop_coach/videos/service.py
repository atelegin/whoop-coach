"""Video service: upsert, usage tracking, last used queries, aggregates."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whoop_coach.db.models import Feedback, PendingLog, User, Video


def canonicalize_youtube_url(video_id: str) -> str:
    """Return canonical YouTube URL for a video ID."""
    return f"https://www.youtube.com/watch?v={video_id}"


async def upsert_video(session: AsyncSession, video_id: str) -> Video:
    """Upsert video: increment usage if exists, create if new.
    
    Args:
        session: Database session (must be in transaction)
        video_id: YouTube video ID (11 chars)
    
    Returns:
        Video instance (new or updated)
    """
    video = await session.get(Video, video_id)
    now = datetime.now(timezone.utc)
    
    if video:
        video.usage_count += 1
        video.last_used_at = now
    else:
        video = Video(
            video_id=video_id,
            usage_count=1,
            first_seen_at=now,
            last_used_at=now,
        )
        session.add(video)
    
    return video


async def get_last_used_video(session: AsyncSession, user_id: UUID) -> Video | None:
    """Get most recently used video for a user.
    
    Query: pending_logs JOIN videos
    WHERE pending_logs.user_id = ? AND pending_logs.video_id IS NOT NULL
    ORDER BY pending_logs.created_at DESC
    LIMIT 1
    
    Args:
        session: Database session
        user_id: User's UUID
    
    Returns:
        Video instance or None if no videos logged
    """
    stmt = (
        select(Video)
        .join(PendingLog, PendingLog.video_id == Video.video_id)
        .where(
            PendingLog.user_id == user_id,
            PendingLog.video_id.isnot(None),
        )
        .order_by(PendingLog.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# === New functions for /video_last with profile aggregates ===

# NOTE: Video.video_id (YouTube ID string) is the PK.
# PendingLog.video_id is a string FK referencing Video.video_id.


async def get_last_video_log(
    session: AsyncSession, user_id: UUID
) -> tuple[Video, PendingLog] | None:
    """Get most recent video and its PendingLog for a user."""
    stmt = (
        select(Video, PendingLog)
        .join(PendingLog, PendingLog.video_id == Video.video_id)
        .where(
            PendingLog.user_id == user_id,
            PendingLog.video_id.isnot(None),
        )
        .order_by(PendingLog.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    return (row[0], row[1]) if row else None


@dataclass
class ProfileAggregate:
    """Aggregate stats for a KB weight profile."""
    heavy_kg: int
    swing_kg: int
    avg_value: float
    count: int

    @property
    def profile_key(self) -> str:
        return f"H{self.heavy_kg}-S{self.swing_kg}"


async def get_video_strain_aggregates_by_profile(
    session: AsyncSession, user_id: UUID, video_id: str
) -> list[ProfileAggregate]:
    """Get avg strain per KB profile for a video.
    
    Excludes rows where kb_heavy_kg_at_time or kb_swing_kg_at_time is NULL.
    Results ordered by count descending (most frequent profile first).
    """
    stmt = (
        select(
            PendingLog.kb_heavy_kg_at_time,
            PendingLog.kb_swing_kg_at_time,
            func.avg(PendingLog.whoop_strain),
            func.count(),
        )
        .where(
            PendingLog.user_id == user_id,
            PendingLog.video_id == video_id,
            PendingLog.whoop_strain.isnot(None),
            PendingLog.kb_heavy_kg_at_time.isnot(None),
            PendingLog.kb_swing_kg_at_time.isnot(None),
        )
        .group_by(PendingLog.kb_heavy_kg_at_time, PendingLog.kb_swing_kg_at_time)
        .order_by(func.count().desc())
    )
    result = await session.execute(stmt)
    return [
        ProfileAggregate(heavy_kg=row[0], swing_kg=row[1], avg_value=row[2], count=row[3])
        for row in result.all()
    ]


async def get_video_effort_aggregates_by_profile(
    session: AsyncSession, user_id: UUID, video_id: str
) -> list[ProfileAggregate]:
    """Get avg effort (RPE) per KB profile for a video.
    
    Excludes rows where kb_heavy_kg_at_time or kb_swing_kg_at_time is NULL.
    Results ordered by count descending (most frequent profile first).
    """
    stmt = (
        select(
            PendingLog.kb_heavy_kg_at_time,
            PendingLog.kb_swing_kg_at_time,
            func.avg(Feedback.rpe_1_5),
            func.count(),
        )
        .join(Feedback, Feedback.pending_log_id == PendingLog.id)
        .where(
            PendingLog.user_id == user_id,
            PendingLog.video_id == video_id,
            Feedback.rpe_1_5.isnot(None),
            PendingLog.kb_heavy_kg_at_time.isnot(None),
            PendingLog.kb_swing_kg_at_time.isnot(None),
        )
        .group_by(PendingLog.kb_heavy_kg_at_time, PendingLog.kb_swing_kg_at_time)
        .order_by(func.count().desc())
    )
    result = await session.execute(stmt)
    return [
        ProfileAggregate(heavy_kg=row[0], swing_kg=row[1], avg_value=row[2], count=row[3])
        for row in result.all()
    ]


@dataclass
class OverallAggregates:
    """Overall aggregates for a video (no profile grouping)."""
    avg_strain: float | None
    strain_count: int
    avg_rpe: float | None
    rpe_count: int


async def get_video_overall_aggregates(
    session: AsyncSession, user_id: UUID, video_id: str
) -> OverallAggregates:
    """Get overall aggregates (no profile grouping) for a video."""
    # Strain (include all rows, even with NULL profile)
    strain_stmt = select(
        func.avg(PendingLog.whoop_strain),
        func.count(),
    ).where(
        PendingLog.user_id == user_id,
        PendingLog.video_id == video_id,
        PendingLog.whoop_strain.isnot(None),
    )
    strain_result = await session.execute(strain_stmt)
    strain_row = strain_result.first()

    # RPE (include all rows)
    rpe_stmt = (
        select(func.avg(Feedback.rpe_1_5), func.count())
        .select_from(PendingLog)
        .join(Feedback, Feedback.pending_log_id == PendingLog.id)
        .where(
            PendingLog.user_id == user_id,
            PendingLog.video_id == video_id,
            Feedback.rpe_1_5.isnot(None),
        )
    )
    rpe_result = await session.execute(rpe_stmt)
    rpe_row = rpe_result.first()

    return OverallAggregates(
        avg_strain=strain_row[0] if strain_row else None,
        strain_count=strain_row[1] if strain_row else 0,
        avg_rpe=rpe_row[0] if rpe_row else None,
        rpe_count=rpe_row[1] if rpe_row else 0,
    )


# === Helper functions ===


def profile_key(heavy: int | None, swing: int | None) -> str:
    """Format KB weight profile key."""
    h = heavy if heavy else "?"
    s = swing if swing else "?"
    return f"H{h}-S{s}"


def format_session_metrics(log: PendingLog) -> str:
    """Format last session metrics line.
    
    Logic:
    - If whoop_workout_id is set (match happened) but no metrics → "смэтчилось, но метрик нет"
    - If whoop_workout_id is NOT set → "не смэтчилось — /retry"
    - Otherwise → show available metrics
    """
    # Check if match happened
    match_happened = log.whoop_workout_id is not None or log.matched_at is not None
    
    parts = []
    
    if log.whoop_strain is not None:
        parts.append(f"strain {log.whoop_strain:.1f}")
    
    if log.whoop_duration_s is not None:
        mins = log.whoop_duration_s // 60
        parts.append(f"{mins} мин")
    
    if log.whoop_hr_avg is not None or log.whoop_hr_max is not None:
        hr_avg = log.whoop_hr_avg or "?"
        hr_max = log.whoop_hr_max or "?"
        parts.append(f"HR {hr_avg}/{hr_max}")
    
    if log.whoop_workout_type:
        parts.append(log.whoop_workout_type)
    
    if parts:
        return "Последняя сессия: " + " · ".join(parts)
    elif match_happened:
        return "Последняя сессия: смэтчилось, но метрик нет"
    else:
        return "Последняя сессия: WHOOP не смэтчилось (пока) — /retry"


def rpe_mean_to_words(mean: float) -> str:
    """Convert RPE mean to Variant C masculine words."""
    if mean < 1.5:
        return "Сделал разминку"
    elif mean < 2.5:
        return "Мог бы сделать ещё одну"
    elif mean < 3.5:
        return "Хватит на сегодня"
    elif mean < 4.5:
        return "Еле дожал"
    else:
        return "Меня вынесло"


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
