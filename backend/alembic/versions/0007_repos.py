"""add repos

Revision ID: 0007_repos
Revises: 0006_users
Create Date: 2026-07-11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_repos"
down_revision: str | None = "0006_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The repository_provider enum type is already created by migration 0002_repositories;
# reused here without a .create()/.drop() call, since that migration owns its lifecycle.
repository_provider = postgresql.ENUM(
    "github",
    "local",
    name="repository_provider",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", repository_provider, nullable=False),
        sa.Column("repo_url", sa.String(length=2048), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("github_owner", sa.String(length=255), nullable=True),
        sa.Column("github_repo", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "repo_url", name="uq_repos_user_id_repo_url"),
    )


def downgrade() -> None:
    op.drop_table("repos")
