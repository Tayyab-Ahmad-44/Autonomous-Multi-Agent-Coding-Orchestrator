from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import RepositoryProvider
from app.schemas.validators import validate_repo_url


class RepoCreate(BaseModel):
    repo_url: str = Field(min_length=1, max_length=2048)
    default_branch: str = Field(default="main", min_length=1, max_length=255)

    _validate_repo_url = field_validator("repo_url")(validate_repo_url)


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    provider: RepositoryProvider
    repo_url: str
    default_branch: str
    github_owner: str | None
    github_repo: str | None
    created_at: datetime
    updated_at: datetime
