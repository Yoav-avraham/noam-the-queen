"""rename sessions.meeting_id to meeting_type_id to match the ORM model

Revision ID: 0006_meeting_type_id_rename
Revises: 0005_status_meeting_lookups
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_meeting_type_id_rename"
down_revision: str | None = "0005_status_meeting_lookups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_sessions_meeting_id_meeting_type", "sessions", type_="foreignkey")
    op.alter_column("sessions", "meeting_id", new_column_name="meeting_type_id")
    op.create_foreign_key(
        "fk_sessions_meeting_type_id_meeting_type",
        "sessions",
        "meeting_type",
        ["meeting_type_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_meeting_type_id_meeting_type", "sessions", type_="foreignkey")
    op.alter_column("sessions", "meeting_type_id", new_column_name="meeting_id")
    op.create_foreign_key(
        "fk_sessions_meeting_id_meeting_type",
        "sessions",
        "meeting_type",
        ["meeting_id"],
        ["id"],
    )
