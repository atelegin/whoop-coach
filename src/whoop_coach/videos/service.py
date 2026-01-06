"""Video service: upsert, usage tracking, last used queries."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whoop_coach.db.models import PendingLog, Video


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
