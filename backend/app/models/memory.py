from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import enum_values


class MemoryScope(str, enum.Enum):
    mission = "mission"
    repo = "repo"
    user = "user"


class MemorySource(str, enum.Enum):
    extracted = "extracted"
    user_stated = "user_stated"


class MemoryStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"


class Memory(Base):
    """A single key/value fact an agent should stay consistent with.

    Three tiers share this table, distinguished by `scope` and by which owner column is set:
      - mission: decisions made inside one mission, visible to later tasks in that mission.
      - repo:    knowledge promoted out of a mission, visible to every later mission on that repo.
      - user:    preferences the user stated explicitly, visible on every repo they own.

    The owner columns (mission_id/repo_id/user_id) cascade on delete; the provenance columns
    (source_*) do not. A promoted repo fact must survive deletion of the mission that taught it,
    so provenance is SET NULL rather than CASCADE.
    """

    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'mission' AND mission_id IS NOT NULL AND repo_id IS NULL AND user_id IS NULL)"
            " OR (scope = 'repo' AND repo_id IS NOT NULL AND mission_id IS NULL AND user_id IS NULL)"
            " OR (scope = 'user' AND user_id IS NOT NULL AND mission_id IS NULL AND repo_id IS NULL)",
            name="ck_memories_owner_matches_scope",
        ),
        # One active fact per key per owner - this is what makes supersession safe: a second
        # active row on the same key cannot exist. Three per-scope partial indexes rather than one
        # composite index over all owner columns, because a unique index treats NULLs as distinct
        # in Postgres, so a composite index over the nullable owner columns would constrain nothing.
        Index(
            "uq_memories_active_mission_key",
            "mission_id",
            "key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'mission'"),
            sqlite_where=text("status = 'active' AND scope = 'mission'"),
        ),
        Index(
            "uq_memories_active_repo_key",
            "repo_id",
            "key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'repo'"),
            sqlite_where=text("status = 'active' AND scope = 'repo'"),
        ),
        Index(
            "uq_memories_active_user_key",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'user'"),
            sqlite_where=text("status = 'active' AND scope = 'user'"),
        ),
        Index("ix_memories_mission_id_status", "mission_id", "status"),
        Index("ix_memories_repo_id_status", "repo_id", "status"),
        Index("ix_memories_user_id_status", "user_id", "status"),
    )

    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[MemoryScope] = mapped_column(
        Enum(MemoryScope, name="memory_scope", values_callable=enum_values),
        nullable=False,
    )

    # Owner: exactly one is set, matching `scope` (see ck_memories_owner_matches_scope).
    mission_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=True,
    )
    repo_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[MemorySource] = mapped_column(
        Enum(MemorySource, name="memory_source", values_callable=enum_values),
        nullable=False,
        default=MemorySource.extracted,
    )
    status: Mapped[MemoryStatus] = mapped_column(
        Enum(MemoryStatus, name="memory_status", values_callable=enum_values),
        nullable=False,
        default=MemoryStatus.active,
    )
    superseded_by_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provenance: where this fact came from. Never CASCADE - a promoted repo fact outlives the
    # mission, milestone and task that produced it.
    source_mission_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_milestone_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("milestones.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_task_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("feature_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
