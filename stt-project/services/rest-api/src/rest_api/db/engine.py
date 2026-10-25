"""Async database engine and session factory helpers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the configured database.

    Args:
        database_url: SQLAlchemy URL (e.g. ``postgresql+asyncpg://...``).

    Returns:
        A configured AsyncEngine with connection health checks enabled.
    """
    return create_async_engine(database_url, pool_pre_ping=True, future=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an async session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
