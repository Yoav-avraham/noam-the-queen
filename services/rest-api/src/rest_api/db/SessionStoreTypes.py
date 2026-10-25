"""Public interface types for the persistence layer.

:class:`SessionView` is an immutable, ORM-free snapshot returned by every
store method.  :class:`SessionStore` is the Protocol that decouples request
handling from SQLAlchemy so routes and the stream handler can be unit-tested
against an in-memory fake.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from datetime import datetime
from dataclasses import dataclass
from collections.abc import Sequence

from ..domain import SessionStatus


@dataclass(frozen=True, slots=True)
class SessionView:
    """Immutable, ORM-free snapshot of a persisted session row."""

    session_id: str
    participant_ids: tuple[str, ...]
    meeting_type: str
    status: str
    text: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class SessionStore(Protocol):
    """Abstract persistence operations for transcription sessions."""

    async def create_session(
        self,
        *,
        session_id: str,
        participant_ids: Sequence[str],
        meeting_type: str,
        status: SessionStatus,
    ) -> SessionView:
        """Insert a new session row and return its snapshot."""
        ...

    async def get_session(self, session_id: str) -> SessionView | None:
        """Return the session snapshot, or None when it does not exist."""
        ...

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update the lifecycle status of an existing session."""
        ...

    async def close_session(
        self,
        session_id: str,
        *,
        text: str,
    ) -> SessionView:
        """Persist the final transcript text and closed status."""
        ...

    async def fail_session(self, session_id: str) -> None:
        """Mark a session as failed."""
        ...
