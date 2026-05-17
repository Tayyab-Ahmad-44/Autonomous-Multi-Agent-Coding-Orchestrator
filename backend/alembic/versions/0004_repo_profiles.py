"""add repo profiles

Revision ID: 0004_repo_profiles
Revises: 0003_mission_events
Create Date: 2026-05-18
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_repo_profiles"
down_revision: str | None = "0003_mission_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frontend_framework", sa.String(length=100), nullable=True),
        sa.Column("backend_framework", sa.String(length=100), nullable=True),
        sa.Column("package_manager", sa.String(length=50), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("test_commands", sa.JSON(), nullable=False),
        sa.Column("build_commands", sa.JSON(), nullable=False),
        sa.Column("important_dirs", sa.JSON(), nullable=False),
        sa.Column("has_docker", sa.Boolean(), nullable=False),
        sa.Column("has_ci", sa.Boolean(), nullable=False),
        sa.Column("readme_summary", sa.Text(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", name="uq_repo_profiles_mission_id"),
    )


def downgrade() -> None:
    op.drop_table("repo_profiles")
