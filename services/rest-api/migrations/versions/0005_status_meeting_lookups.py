"""add meeting_type and session_status lookup tables

Revision ID: 0005_status_meeting_lookups
Revises: 0004_participant_ids_array
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_status_meeting_lookups"
down_revision: str | None = "0004_participant_ids_array"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEETING_TYPES = ["waiting", "processing", "screening", "done", "failed"]
_SESSION_STATUSES = ["created", "streaming", "processing", "closed", "failed"]


def upgrade() -> None:
    meeting_type = op.create_table(
        "meeting_type",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    session_status = op.create_table(
        "session_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.bulk_insert(meeting_type, [{"id": i, "code": code} for i, code in enumerate(_MEETING_TYPES, 1)])
    op.bulk_insert(session_status, [{"id": i, "code": code} for i, code in enumerate(_SESSION_STATUSES, 1)])

    # Postgres forbids subqueries in ALTER COLUMN ... USING, so convert the
    # free-text columns to integer FKs via temporary columns + UPDATE.

    # status (text) -> status_id (int FK to session_status)
    op.add_column("sessions", sa.Column("status_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE sessions SET status_id = "
        "(SELECT id FROM session_status WHERE session_status.code = sessions.status)"
    )
    op.alter_column("sessions", "status_id", nullable=False)
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_column("sessions", "status")
    op.create_foreign_key(
        "fk_sessions_status_id_session_status",
        "sessions",
        "session_status",
        ["status_id"],
        ["id"],
    )
    op.create_index("ix_sessions_status_id", "sessions", ["status_id"])

    # meeting_id (text) -> meeting_id (int FK to meeting_type)
    op.add_column("sessions", sa.Column("meeting_id_fk", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE sessions SET meeting_id_fk = "
        "(SELECT id FROM meeting_type WHERE meeting_type.code = sessions.meeting_id)"
    )
    op.alter_column("sessions", "meeting_id_fk", nullable=False)
    op.drop_column("sessions", "meeting_id")
    op.alter_column("sessions", "meeting_id_fk", new_column_name="meeting_id")
    op.create_foreign_key(
        "fk_sessions_meeting_id_meeting_type",
        "sessions",
        "meeting_type",
        ["meeting_id"],
        ["id"],
    )


def downgrade() -> None:
    # meeting_id (int FK) -> meeting_id (text code)
    op.drop_constraint("fk_sessions_meeting_id_meeting_type", "sessions", type_="foreignkey")
    op.add_column("sessions", sa.Column("meeting_id_code", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE sessions SET meeting_id_code = "
        "(SELECT code FROM meeting_type WHERE meeting_type.id = sessions.meeting_id)"
    )
    op.alter_column("sessions", "meeting_id_code", nullable=False)
    op.drop_column("sessions", "meeting_id")
    op.alter_column("sessions", "meeting_id_code", new_column_name="meeting_id")

    # status_id (int FK) -> status (text code)
    op.drop_index("ix_sessions_status_id", table_name="sessions")
    op.drop_constraint("fk_sessions_status_id_session_status", "sessions", type_="foreignkey")
    op.add_column("sessions", sa.Column("status", sa.String(length=32), nullable=True))
    op.execute(
        "UPDATE sessions SET status = "
        "(SELECT code FROM session_status WHERE session_status.id = sessions.status_id)"
    )
    op.alter_column("sessions", "status", nullable=False)
    op.drop_column("sessions", "status_id")
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.drop_table("session_status")
    op.drop_table("meeting_type")
