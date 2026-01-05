"""Database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whoop_coach.config import get_settings

settings = get_settings()


def get_async_database_url(url: str) -> str:
    """Convert DATABASE_URL to async-compatible format.
    
    - postgresql:// → postgresql+asyncpg://
    - sqlite:// → sqlite+aiosqlite://
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        # Railway sometimes uses postgres:// instead of postgresql://
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


engine = create_async_engine(
    get_async_database_url(settings.DATABASE_URL),
    echo=settings.is_dev,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI — yields an async session."""
    async with async_session_factory() as session:
        async with session.begin():
            yield session

