"""add missions owner_id and repo_id

Revision ID: 0008_missions_owner_and_repo
Revises: 0007_repos
Create Date: 2026-07-12

This migration requires the missions table to be empty: owner_id/repo_id are
added NOT NULL with no server default, and there is no legitimate owner to
backfill onto pre-existing rows (this codebase is pre-production, with no
real users yet). Wipe the dev database (e.g. `TRUNCATE missions CASCADE` or a
full drop/recreate) before running this migration.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008_missions_owner_and_repo"
down_revision: str | None = "0007_repos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.add_column("missions", sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.create_foreign_key(
        "fk_missions_owner_id",
        "missions",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_missions_repo_id",
        "missions",
        "repos",
        ["repo_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_missions_repo_id", "missions", type_="foreignkey")
    op.drop_constraint("fk_missions_owner_id", "missions", type_="foreignkey")
    op.drop_column("missions", "repo_id")
    op.drop_column("missions", "owner_id")
