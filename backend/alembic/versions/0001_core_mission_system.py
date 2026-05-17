"""create core mission system

Revision ID: 0001_core_mission_system
Revises:
Create Date: 2026-05-17
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_core_mission_system"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


mission_status = postgresql.ENUM(
    "draft",
    "planning",
    "waiting_for_approval",
    "running",
    "validating",
    "failed",
    "completed",
    name="mission_status",
    create_type=False,
)
milestone_status = postgresql.ENUM(
    "pending",
    "running",
    "validating",
    "failed",
    "completed",
    name="milestone_status",
    create_type=False,
)
feature_task_type = postgresql.ENUM(
    "planning",
    "research",
    "backend",
    "frontend",
    "database",
    "test",
    "docs",
    "fix",
    name="feature_task_type",
    create_type=False,
)
feature_task_status = postgresql.ENUM(
    "pending",
    "running",
    "failed",
    "completed",
    name="feature_task_status",
    create_type=False,
)
agent_run_status = postgresql.ENUM(
    "queued",
    "running",
    "failed",
    "completed",
    name="agent_run_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    mission_status.create(bind, checkfirst=True)
    milestone_status.create(bind, checkfirst=True)
    feature_task_type.create(bind, checkfirst=True)
    feature_task_status.create(bind, checkfirst=True)
    agent_run_status.create(bind, checkfirst=True)

    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", mission_status, nullable=False),
        sa.Column("current_milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", milestone_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_missions_current_milestone_id",
        "missions",
        "milestones",
        ["current_milestone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "feature_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("task_type", feature_task_type, nullable=False),
        sa.Column("status", feature_task_status, nullable=False),
        sa.Column("assigned_agent_type", sa.String(length=100), nullable=True),
        sa.Column("depends_on", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["milestone_id"], ["milestones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "validation_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("required_tests", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_type", sa.String(length=100), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("status", agent_run_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["feature_task_id"], ["feature_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "validation_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validator_type", sa.String(length=100), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["milestone_id"], ["milestones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("validation_reports")
    op.drop_table("agent_runs")
    op.drop_table("validation_contracts")
    op.drop_table("feature_tasks")
    op.drop_constraint("fk_missions_current_milestone_id", "missions", type_="foreignkey")
    op.drop_table("milestones")
    op.drop_table("missions")

    bind = op.get_bind()
    agent_run_status.drop(bind, checkfirst=True)
    feature_task_status.drop(bind, checkfirst=True)
    feature_task_type.drop(bind, checkfirst=True)
    milestone_status.drop(bind, checkfirst=True)
    mission_status.drop(bind, checkfirst=True)
