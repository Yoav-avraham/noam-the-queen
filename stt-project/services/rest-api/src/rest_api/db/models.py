"""SQLAlchemy ORM models for rest API session persistence."""

from __future__ import annotations

from typing import Any
from datetime import datetime

from sqlalchemy import Text, Uuid, String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, DeclarativeBase, relationship, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY


class Base(DeclarativeBase):
    """Declarative base for all rest API ORM models."""


class SessionStatusRecord(Base):
    """Seeded lookup of valid session lifecycle statuses."""

    __tablename__ = "session_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class SessionRecord(Base):
    """Persisted transcription session and its lifecycle metadata."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    participant_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status_id: Mapped[int] = mapped_column(ForeignKey("session_status.id"), nullable=False)
    status_ref: Mapped[SessionStatusRecord] = relationship(lazy="joined")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def metadata_dict() -> dict[str, Any]:
    """Return a serialisable view of table names (used in diagnostics/tests)."""
    return {name: table.name for name, table in Base.metadata.tables.items()}
