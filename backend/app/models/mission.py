from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_class]


class MissionStatus(str, enum.Enum):
    draft = "draft"
    planning = "planning"
    waiting_for_approval = "waiting_for_approval"
    running = "running"
    validating = "validating"
    failed = "failed"
    completed = "completed"


class MilestoneStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    validating = "validating"
    failed = "failed"
    completed = "completed"


class FeatureTaskType(str, enum.Enum):
    planning = "planning"
    research = "research"
    backend = "backend"
    frontend = "frontend"
    database = "database"
    test = "test"
    docs = "docs"
    fix = "fix"


class FeatureTaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    failed = "failed"
    completed = "completed"


class AgentRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    completed = "completed"


class RepositoryProvider(str, enum.Enum):
    github = "github"
    local = "local"


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus, name="mission_status", values_callable=enum_values),
        nullable=False,
        default=MissionStatus.draft,
    )
    current_milestone_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "milestones.id",
            name="fk_missions_current_milestone_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    current_milestone: Mapped[Milestone | None] = relationship(
        "Milestone",
        foreign_keys=[current_milestone_id],
        post_update=True,
    )
    milestones: Mapped[list[Milestone]] = relationship(
        "Milestone",
        back_populates="mission",
        cascade="all, delete-orphan",
        foreign_keys="Milestone.mission_id",
    )
    feature_tasks: Mapped[list[FeatureTask]] = relationship(
        "FeatureTask",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    validation_contracts: Mapped[list[ValidationContract]] = relationship(
        "ValidationContract",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        "AgentRun",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    validation_reports: Mapped[list[ValidationReport]] = relationship(
        "ValidationReport",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    events: Mapped[list[MissionEvent]] = relationship(
        "MissionEvent",
        back_populates="mission",
        cascade="all, delete-orphan",
    )
    repository: Mapped[Repository | None] = relationship(
        "Repository",
        back_populates="mission",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MilestoneStatus] = mapped_column(
        Enum(MilestoneStatus, name="milestone_status", values_callable=enum_values),
        nullable=False,
        default=MilestoneStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship(
        "Mission",
        back_populates="milestones",
        foreign_keys=[mission_id],
    )
    feature_tasks: Mapped[list[FeatureTask]] = relationship(
        "FeatureTask",
        back_populates="milestone",
    )
    validation_reports: Mapped[list[ValidationReport]] = relationship(
        "ValidationReport",
        back_populates="milestone",
    )


class FeatureTask(Base):
    __tablename__ = "feature_tasks"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    milestone_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("milestones.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[FeatureTaskType] = mapped_column(
        Enum(FeatureTaskType, name="feature_task_type", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[FeatureTaskStatus] = mapped_column(
        Enum(FeatureTaskStatus, name="feature_task_status", values_callable=enum_values),
        nullable=False,
        default=FeatureTaskStatus.pending,
    )
    assigned_agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    depends_on: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="feature_tasks")
    milestone: Mapped[Milestone | None] = relationship("Milestone", back_populates="feature_tasks")
    agent_runs: Mapped[list[AgentRun]] = relationship(
        "AgentRun",
        back_populates="feature_task",
    )


class ValidationContract(Base):
    __tablename__ = "validation_contracts"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    required_tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="validation_contracts")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_task_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("feature_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status", values_callable=enum_values),
        nullable=False,
        default=AgentRunStatus.queued,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="agent_runs")
    feature_task: Mapped[FeatureTask | None] = relationship("FeatureTask", back_populates="agent_runs")
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact",
        back_populates="agent_run",
    )


class ValidationReport(Base):
    __tablename__ = "validation_reports"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    milestone_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("milestones.id", ondelete="SET NULL"),
        nullable=True,
    )
    validator_type: Mapped[str] = mapped_column(String(100), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="validation_reports")
    milestone: Mapped[Milestone | None] = relationship("Milestone", back_populates="validation_reports")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_run_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    artifact_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="artifacts")
    agent_run: Mapped[AgentRun | None] = relationship("AgentRun", back_populates="artifacts")


class MissionEvent(Base):
    __tablename__ = "mission_events"

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="events")


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("mission_id", name="uq_repositories_mission_id"),)

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mission_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[RepositoryProvider] = mapped_column(
        Enum(RepositoryProvider, name="repository_provider", values_callable=enum_values),
        nullable=False,
    )
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    github_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    mission: Mapped[Mission] = relationship("Mission", back_populates="repository")
