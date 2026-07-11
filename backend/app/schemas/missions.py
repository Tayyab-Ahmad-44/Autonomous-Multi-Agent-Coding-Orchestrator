from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    AgentRunStatus,
    FeatureTaskStatus,
    FeatureTaskType,
    MilestoneStatus,
    MissionStatus,
    RepositoryProvider,
)
class RepositoryCloneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    provider: RepositoryProvider
    repo_url: str
    default_branch: str
    local_path: str | None
    github_owner: str | None
    github_repo: str | None
    created_at: datetime
    current_branch: str


class MissionCreate(BaseModel):
    repo_id: UUID
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1)


class MissionStatusUpdate(BaseModel):
    status: MissionStatus


class MissionPlanRejection(BaseModel):
    feedback: str = Field(min_length=1)


class RepositoryCreate(BaseModel):
    provider: RepositoryProvider
    repo_url: str = Field(min_length=1, max_length=2048)
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    local_path: str | None = Field(default=None, max_length=1024)
    github_owner: str | None = Field(default=None, max_length=255)
    github_repo: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_local_provider(self) -> "RepositoryCreate":
        if self.provider == RepositoryProvider.local and not self.local_path:
            raise ValueError("local_path is required for local repositories.")
        return self


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    provider: RepositoryProvider
    repo_url: str
    default_branch: str
    local_path: str | None
    github_owner: str | None
    github_repo: str | None
    created_at: datetime


class MissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    repo_id: UUID
    title: str
    goal: str
    status: MissionStatus
    current_milestone_id: UUID | None
    created_at: datetime
    updated_at: datetime


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    name: str
    description: str
    order_index: int
    status: MilestoneStatus
    created_at: datetime
    updated_at: datetime


class FeatureTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    milestone_id: UUID | None
    title: str
    description: str
    task_type: FeatureTaskType
    status: FeatureTaskStatus
    assigned_agent_type: str | None
    depends_on: list[str] | None
    created_at: datetime
    updated_at: datetime


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    feature_task_id: UUID | None
    agent_type: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    status: AgentRunStatus
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ValidationContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    content: str
    assertions: list[dict[str, Any]]
    required_tests: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ValidationReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    milestone_id: UUID | None
    validator_type: str
    passed: bool
    summary: str
    issues: list[dict[str, Any]]
    raw_output: dict[str, Any] | None
    created_at: datetime


class MissionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    event_type: str
    message: str
    payload: dict[str, Any] | None
    created_at: datetime


class RepoProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mission_id: UUID
    frontend_framework: str | None
    backend_framework: str | None
    package_manager: str | None
    language: str | None
    test_commands: list[str]
    build_commands: list[str]
    important_dirs: list[str]
    has_docker: bool
    has_ci: bool
    readme_summary: str | None
    created_at: datetime
    updated_at: datetime


class MissionDetailRead(MissionRead):
    milestones: list[MilestoneRead]
    feature_tasks: list[FeatureTaskRead]
    validation_contract: ValidationContractRead | None
    validation_reports: list[ValidationReportRead]
    events: list[MissionEventRead]
    repo_profile: RepoProfileRead | None = None


class OpenPrResponse(BaseModel):
    pr_url: str
    branch: str
