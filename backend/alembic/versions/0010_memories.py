"""add memories and absorb mission_decisions

Revision ID: 0010_memories
Revises: 0009_repositories_repo_id
Create Date: 2026-07-12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_memories"
down_revision: str | None = "0009_repositories_repo_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


memory_scope = postgresql.ENUM(
    "mission",
    "repo",
    "user",
    name="memory_scope",
    create_type=False,
)
memory_source = postgresql.ENUM(
    "extracted",
    "user_stated",
    name="memory_source",
    create_type=False,
)
memory_status = postgresql.ENUM(
    "active",
    "superseded",
    name="memory_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    memory_scope.create(bind, checkfirst=True)
    memory_source.create(bind, checkfirst=True)
    memory_status.create(bind, checkfirst=True)

    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", memory_scope, nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("source", memory_source, nullable=False),
        sa.Column("status", memory_status, nullable=False),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_mission_id"], ["missions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_milestone_id"], ["milestones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_task_id"], ["feature_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(scope = 'mission' AND mission_id IS NOT NULL AND repo_id IS NULL AND user_id IS NULL)"
            " OR (scope = 'repo' AND repo_id IS NOT NULL AND mission_id IS NULL AND user_id IS NULL)"
            " OR (scope = 'user' AND user_id IS NOT NULL AND mission_id IS NULL AND repo_id IS NULL)",
            name="ck_memories_owner_matches_scope",
        ),
    )

    # One active fact per key per owner. Partial unique indexes, one per scope: a single composite
    # index over the nullable owner columns would not constrain anything, because Postgres treats
    # NULLs as distinct in a unique index.
    op.create_index(
        "uq_memories_active_mission_key",
        "memories",
        ["mission_id", "key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND scope = 'mission'"),
    )
    op.create_index(
        "uq_memories_active_repo_key",
        "memories",
        ["repo_id", "key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND scope = 'repo'"),
    )
    op.create_index(
        "uq_memories_active_user_key",
        "memories",
        ["user_id", "key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND scope = 'user'"),
    )
    op.create_index("ix_memories_mission_id_status", "memories", ["mission_id", "status"])
    op.create_index("ix_memories_repo_id_status", "memories", ["repo_id", "status"])
    op.create_index("ix_memories_user_id_status", "memories", ["user_id", "status"])

    # Backfill: every existing mission_decision becomes an active, extracted, mission-scoped memory.
    #
    # DISTINCT ON collapses duplicate keys within a mission, keeping the most recent - the old table
    # allowed several rows on the same key (nothing deduped, and every row was injected into
    # prompts). The new partial unique index forbids that, so the losers are dropped rather than
    # migrated as superseded: they were never modelled as supersessions, only as noise.
    op.execute(
        sa.text(
            """
            INSERT INTO memories (
                id, scope, mission_id, key, value, source, status,
                source_mission_id, source_task_id, created_at
            )
            SELECT DISTINCT ON (d.mission_id, d.key)
                d.id,
                'mission',
                d.mission_id,
                d.key,
                d.value,
                'extracted',
                'active',
                d.mission_id,
                d.source_task_id,
                d.created_at
            FROM mission_decisions AS d
            ORDER BY d.mission_id, d.key, d.created_at DESC
            """
        )
    )

    op.drop_index("ix_mission_decisions_mission_id_created_at", table_name="mission_decisions")
    op.drop_table("mission_decisions")


def downgrade() -> None:
    op.create_table(
        "mission_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_task_id"], ["feature_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mission_decisions_mission_id_created_at",
        "mission_decisions",
        ["mission_id", "created_at"],
    )

    # Only mission-scoped memories have a home in the old table; promoted repo and user memories
    # are dropped by this downgrade.
    op.execute(
        sa.text(
            """
            INSERT INTO mission_decisions (id, mission_id, source_task_id, key, value, created_at)
            SELECT m.id, m.mission_id, m.source_task_id, m.key, m.value, m.created_at
            FROM memories AS m
            WHERE m.scope = 'mission' AND m.mission_id IS NOT NULL
            """
        )
    )

    op.drop_index("ix_memories_user_id_status", table_name="memories")
    op.drop_index("ix_memories_repo_id_status", table_name="memories")
    op.drop_index("ix_memories_mission_id_status", table_name="memories")
    op.drop_index("uq_memories_active_user_key", table_name="memories")
    op.drop_index("uq_memories_active_repo_key", table_name="memories")
    op.drop_index("uq_memories_active_mission_key", table_name="memories")
    op.drop_table("memories")

    bind = op.get_bind()
    memory_status.drop(bind, checkfirst=True)
    memory_source.drop(bind, checkfirst=True)
    memory_scope.drop(bind, checkfirst=True)
