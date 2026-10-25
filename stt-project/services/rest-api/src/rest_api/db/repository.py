"""Persistence access layer for transcription sessions.

:class:`SqlAlchemySessionStore` is the production implementation of the
:class:`SessionStore` protocol defined in :mod:`.types`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import SessionRecord, SessionStatusRecord
from ..domain import ErrorKey, RestApiError, SessionStatus
from .SessionStoreTypes import SessionView

logger = logging.getLogger(__name__)


def _to_view(record: SessionRecord) -> SessionView:
    """Convert an ORM row into an immutable snapshot."""
    return SessionView(
        session_id=record.session_id,
        participant_ids=tuple(record.participant_ids),
        meeting_type=record.meeting_type,
        status=record.status_ref.code,
        text=record.text,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemySessionStore:
    """SQLAlchemy-backed implementation of :class:`SessionStore`."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create_session(
        self,
        *,
        session_id: str,
        participant_ids: Sequence[str],
        meeting_type: str,
        status: SessionStatus,
    ) -> SessionView:
        async with self._sessionmaker() as db:
            record = SessionRecord(
                session_id=session_id,
                participant_ids=list(participant_ids),
                meeting_type=meeting_type,
                status_ref=await self._status_row(db, status),
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            return _to_view(record)

    async def get_session(self, session_id: str) -> SessionView | None:
        async with self._sessionmaker() as db:
            record = await db.get(SessionRecord, session_id)
            return _to_view(record) if record is not None else None

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        async with self._sessionmaker() as db:
            record = await self._require(db, session_id)
            record.status_ref = await self._status_row(db, status)
            await db.commit()

    async def close_session(
        self,
        session_id: str,
        *,
        text: str,
    ) -> SessionView:
        async with self._sessionmaker() as db:
            record = await self._require(db, session_id)
            record.status_ref = await self._status_row(db, SessionStatus.CLOSED)
            record.text = text
            await db.commit()
            await db.refresh(record)
            return _to_view(record)

    async def fail_session(self, session_id: str) -> None:
        async with self._sessionmaker() as db:
            record = await self._require(db, session_id)
            record.status_ref = await self._status_row(db, SessionStatus.FAILED)
            await db.commit()

    @staticmethod
    async def _status_row(db: AsyncSession, status: SessionStatus) -> SessionStatusRecord:
        result = await db.execute(select(SessionStatusRecord).where(SessionStatusRecord.code == str(status)))
        return result.scalar_one()

    @staticmethod
    async def _require(db: AsyncSession, session_id: str) -> SessionRecord:
        record = await db.get(SessionRecord, session_id)
        if record is None:
            raise RestApiError(key=ErrorKey.SESSION_NOT_FOUND)
        return record
