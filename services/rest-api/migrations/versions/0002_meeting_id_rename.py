"""rename interview_type to meeting_id and drop scheduled_at

Revision ID: 0002_meeting_id_rename
Revises: 0001_initial
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_meeting_id_rename"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("sessions", "interview_type", new_column_name="meeting_id")
    op.drop_column("sessions", "scheduled_at")


def downgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.alter_column("sessions", "meeting_id", new_column_name="interview_type")
