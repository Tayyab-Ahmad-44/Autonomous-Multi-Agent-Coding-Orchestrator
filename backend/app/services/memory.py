"""Storage for the three memory tiers (mission, repo, user).

All three share one table and one code path; see app.models.memory.Memory. Writes go through
`record_memory`, which supersedes rather than duplicates: a second active fact on the same key for
the same owner cannot exist (enforced by a partial unique index), so recording `auth_scheme: OAuth`
over an existing `auth_scheme: JWT` marks the old row superseded and keeps it for audit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, MemoryScope, MemorySource, MemoryStatus


# Defensive bound on how much memory a single prompt can carry. Not a relevance filter - at
# realistic sizes (tens of facts) everything is injected. This exists so that a misbehaving
# promotion pass degrades into a truncated prompt instead of an enormous one.
MEMORY_READ_LIMIT = 50


_OWNER_COLUMN = {
    MemoryScope.mission: Memory.mission_id,
    MemoryScope.repo: Memory.repo_id,
    MemoryScope.user: Memory.user_id,
}


def list_memories(
    db: Session,
    *,
    scope: MemoryScope,
    owner_id: UUID,
    limit: int = MEMORY_READ_LIMIT,
) -> list[Memory]:
    """Active facts for one owner, oldest first, newest kept when truncating."""
    owner_column = _OWNER_COLUMN[scope]
    statement = (
        select(Memory)
        .where(
            Memory.scope == scope,
            owner_column == owner_id,
            Memory.status == MemoryStatus.active,
        )
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    memories = list(db.scalars(statement).all())
    memories.reverse()
    return memories


def record_memory(
    db: Session,
    *,
    scope: MemoryScope,
    owner_id: UUID,
    key: str,
    value: str,
    source: MemorySource = MemorySource.extracted,
    source_mission_id: UUID | None = None,
    source_milestone_id: UUID | None = None,
    source_task_id: UUID | None = None,
) -> Memory:
    """Record a fact, superseding any active fact on the same key for the same owner."""
    existing = get_active_memory_by_key(db, scope=scope, owner_id=owner_id, key=key)

    # Retire the old row before inserting the new one. The partial unique index forbids two active
    # rows on the same key, so inserting first would trip it - the constraint is doing its job.
    if existing is not None:
        existing.status = MemoryStatus.superseded
        existing.superseded_at = datetime.now(timezone.utc)
        db.flush()

    memory = Memory(
        scope=scope,
        key=key,
        value=value,
        source=source,
        status=MemoryStatus.active,
        source_mission_id=source_mission_id,
        source_milestone_id=source_milestone_id,
        source_task_id=source_task_id,
    )
    setattr(memory, _OWNER_COLUMN[scope].key, owner_id)
    db.add(memory)
    db.flush()

    if existing is not None:
        existing.superseded_by_id = memory.id

    db.commit()
    db.refresh(memory)
    return memory


def get_memory(db: Session, memory_id: UUID) -> Memory | None:
    return db.get(Memory, memory_id)


def get_active_memory_by_key(
    db: Session,
    *,
    scope: MemoryScope,
    owner_id: UUID,
    key: str,
) -> Memory | None:
    owner_column = _OWNER_COLUMN[scope]
    statement = select(Memory).where(
        Memory.scope == scope,
        owner_column == owner_id,
        Memory.key == key,
        Memory.status == MemoryStatus.active,
    )
    return db.scalars(statement).first()


def forget_memory(db: Session, memory_id: UUID) -> Memory | None:
    """Retire a fact without replacing it. Used by the explicit user-preference endpoint;
    the promotion pass never calls this - it supersedes through `record_memory` instead."""
    memory = db.get(Memory, memory_id)
    if memory is None or memory.status == MemoryStatus.superseded:
        return memory

    memory.status = MemoryStatus.superseded
    memory.superseded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(memory)
    return memory
