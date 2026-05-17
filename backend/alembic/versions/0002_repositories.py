"""add repositories

Revision ID: 0002_repositories
Revises: 0001_core_mission_system
Create Date: 2026-05-17
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_repositories"
down_revision: str | None = "0001_core_mission_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


repository_provider = postgresql.ENUM(
    "github",
    "local",
    name="repository_provider",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    repository_provider.create(bind, checkfirst=True)

    op.create_table(
        "repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", repository_provider, nullable=False),
        sa.Column("repo_url", sa.String(length=2048), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("github_owner", sa.String(length=255), nullable=True),
        sa.Column("github_repo", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", name="uq_repositories_mission_id"),
    )


def downgrade() -> None:
    op.drop_table("repositories")
    bind = op.get_bind()
    repository_provider.drop(bind, checkfirst=True)
