"""add mission events

Revision ID: 0003_mission_events
Revises: 0002_repositories
Create Date: 2026-05-17
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_mission_events"
down_revision: str | None = "0002_repositories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mission_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mission_events_mission_id_created_at", "mission_events", ["mission_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_mission_events_mission_id_created_at", table_name="mission_events")
    op.drop_table("mission_events")
