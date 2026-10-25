"""convert participant_ids from json to text[]

Revision ID: 0004_participant_ids_array
Revises: 0003_text_column_drop_segments
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_participant_ids_array"
down_revision: str | None = "0003_text_column_drop_segments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres forbids subqueries in ALTER COLUMN ... USING, so convert via a
    # temporary column populated with an UPDATE (which may contain subqueries).
    op.add_column(
        "sessions",
        sa.Column("participant_ids_arr", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.execute(
        "UPDATE sessions SET participant_ids_arr = COALESCE("
        "(SELECT array_agg(elem) "
        "FROM jsonb_array_elements_text(participant_ids::jsonb) AS elem), "
        "ARRAY[]::text[])"
    )
    op.alter_column("sessions", "participant_ids_arr", nullable=False)
    op.drop_column("sessions", "participant_ids")
    op.alter_column("sessions", "participant_ids_arr", new_column_name="participant_ids")


def downgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("participant_ids_json", sa.JSON(), nullable=True),
    )
    op.execute("UPDATE sessions SET participant_ids_json = to_jsonb(participant_ids)")
    op.alter_column("sessions", "participant_ids_json", nullable=False)
    op.drop_column("sessions", "participant_ids")
    op.alter_column("sessions", "participant_ids_json", new_column_name="participant_ids")
