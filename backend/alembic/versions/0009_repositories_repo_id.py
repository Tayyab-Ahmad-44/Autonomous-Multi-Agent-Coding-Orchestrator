"""add repositories repo_id

Revision ID: 0009_repositories_repo_id
Revises: 0008_missions_owner_and_repo
Create Date: 2026-07-12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009_repositories_repo_id"
down_revision: str | None = "0008_missions_owner_and_repo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_repositories_repo_id",
        "repositories",
        "repos",
        ["repo_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_repositories_repo_id", "repositories", type_="foreignkey")
    op.drop_column("repositories", "repo_id")
