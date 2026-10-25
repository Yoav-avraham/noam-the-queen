"""replace meeting_type lookup FK with free-form meeting_type strings

Revision ID: 0007_dynamic_meeting_types
Revises: 0006_meeting_type_id_rename
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_dynamic_meeting_types"
down_revision: str | None = "0006_meeting_type_id_rename"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_sessions_meeting_type_id_meeting_type", "sessions", type_="foreignkey")
    op.add_column("sessions", sa.Column("meeting_type", sa.String(length=64), nullable=True))
    op.execute(
        "UPDATE sessions SET meeting_type = "
        "(SELECT code FROM meeting_type WHERE meeting_type.id = sessions.meeting_type_id)"
    )
    op.alter_column("sessions", "meeting_type", nullable=False)
    op.drop_column("sessions", "meeting_type_id")
    op.drop_table("meeting_type")


def downgrade() -> None:
    meeting_type = op.create_table(
        "meeting_type",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.execute(
        "INSERT INTO meeting_type (code) "
        "SELECT DISTINCT meeting_type FROM sessions ORDER BY meeting_type"
    )
    op.add_column("sessions", sa.Column("meeting_type_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE sessions SET meeting_type_id = "
        "(SELECT id FROM meeting_type WHERE meeting_type.code = sessions.meeting_type)"
    )
    op.alter_column("sessions", "meeting_type_id", nullable=False)
    op.drop_column("sessions", "meeting_type")
    op.create_foreign_key(
        "fk_sessions_meeting_type_id_meeting_type",
        "sessions",
        "meeting_type",
        ["meeting_type_id"],
        ["id"],
    )
