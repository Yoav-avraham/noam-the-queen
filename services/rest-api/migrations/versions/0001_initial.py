"""initial session and transcript_segments tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("participant_ids", sa.JSON(), nullable=False),
        sa.Column("interview_type", sa.String(length=255), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stream_api_session_id", sa.String(length=255), nullable=True),
        sa.Column("audio_object_key", sa.String(length=1024), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcript_segments_session_id",
        "transcript_segments",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_segments_session_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_table("sessions")
