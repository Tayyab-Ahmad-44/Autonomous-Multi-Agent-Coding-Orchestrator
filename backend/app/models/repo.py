from __future__ import annotations

from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import RepositoryProvider, enum_values


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("user_id", "repo_url", name="uq_repos_user_id_repo_url"),)

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[RepositoryProvider] = mapped_column(
        Enum(RepositoryProvider, name="repository_provider", values_callable=enum_values),
        nullable=False,
    )
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    github_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
