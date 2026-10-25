"""Tests for the SQLAlchemy session store against a Postgres container."""

from __future__ import annotations

import os
from uuid import uuid4
from typing import TYPE_CHECKING
from collections.abc import Iterator, AsyncIterator

# The Ryuk reaper container needs a host port mapping that is unavailable in
# some Docker setups; disable it and rely on the context manager for cleanup.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from rest_api.db import (
    Base,
    SessionStatusRecord,
    SqlAlchemySessionStore,
)
from rest_api.domain import ErrorKey, RestApiError, SessionStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SESSION_STATUSES = {
    1: "created",
    2: "streaming",
    3: "processing",
    4: "closed",
    5: "failed",
}
SCREENING_MEETING_TYPE = "screening"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # participant_ids uses a Postgres ARRAY column, so the store is tested
    # against a real Postgres instead of SQLite.
    with PostgresContainer(
        "postgres:15-alpine",
        username="test",
        password="test",
        dbname="test",
        driver="asyncpg",
    ) as postgres:
        yield postgres.get_connection_url()


@pytest_asyncio.fixture
async def store(postgres_url: str) -> AsyncIterator[SqlAlchemySessionStore]:
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        db.add_all([SessionStatusRecord(id=key, code=code) for key, code in _SESSION_STATUSES.items()])
        await db.commit()
    try:
        yield SqlAlchemySessionStore(sessionmaker)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _seed(store: SqlAlchemySessionStore) -> str:
    session_id = str(uuid4())
    await store.create_session(
        session_id=session_id,
        participant_ids=["alice", "bob"],
        meeting_type=SCREENING_MEETING_TYPE,
        status=SessionStatus.CREATED,
    )
    return session_id


@pytest.mark.asyncio
async def test_create_and_get_session(store: SqlAlchemySessionStore) -> None:
    session_id = await _seed(store)
    view = await store.get_session(session_id)
    assert view is not None
    assert view.participant_ids == ("alice", "bob")
    assert view.meeting_type == SCREENING_MEETING_TYPE
    assert view.status == "created"


@pytest.mark.asyncio
async def test_get_missing_returns_none(store: SqlAlchemySessionStore) -> None:
    assert await store.get_session(str(uuid4())) is None


@pytest.mark.asyncio
async def test_update_status(store: SqlAlchemySessionStore) -> None:
    session_id = await _seed(store)
    await store.update_status(session_id, SessionStatus.STREAMING)
    view = await store.get_session(session_id)
    assert view is not None and view.status == "streaming"


@pytest.mark.asyncio
async def test_close_session_persists_text(
    store: SqlAlchemySessionStore,
) -> None:
    session_id = await _seed(store)
    view = await store.close_session(session_id, text="hello")
    assert view.status == "closed"
    assert view.text == "hello"


@pytest.mark.asyncio
async def test_fail_session(store: SqlAlchemySessionStore) -> None:
    session_id = await _seed(store)
    await store.fail_session(session_id)
    view = await store.get_session(session_id)
    assert view is not None and view.status == "failed"


@pytest.mark.asyncio
async def test_update_status_missing_raises(store: SqlAlchemySessionStore) -> None:
    with pytest.raises(RestApiError) as exc:
        await store.update_status(str(uuid4()), SessionStatus.CLOSED)
    assert exc.value.key is ErrorKey.SESSION_NOT_FOUND
