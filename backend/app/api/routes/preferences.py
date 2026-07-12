from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import MemoryScope, MemorySource
from app.schemas import PreferenceCreate, PreferenceRead
from app.services import memory as memory_service


router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.post("", response_model=PreferenceRead, status_code=status.HTTP_201_CREATED)
def upsert_preference(
    payload: PreferenceCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> PreferenceRead:
    """State a preference. Re-stating an existing key supersedes the old value.

    Preferences are user-stated, never extracted: nothing in the orchestrator infers them, and
    neither the promotion pass nor any eviction may retire them. Only the user can, via DELETE.
    """
    return memory_service.record_memory(
        db,
        scope=MemoryScope.user,
        owner_id=current_user.id,
        key=payload.key,
        value=payload.value,
        source=MemorySource.user_stated,
    )


@router.get("", response_model=list[PreferenceRead])
def list_preferences(current_user: CurrentUser, db: DbSession) -> list[PreferenceRead]:
    return memory_service.list_memories(db, scope=MemoryScope.user, owner_id=current_user.id)


@router.delete("/{preference_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preference(preference_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    preference = memory_service.get_memory(db, preference_id)
    if (
        preference is None
        or preference.scope != MemoryScope.user
        or preference.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preference not found")

    memory_service.forget_memory(db, preference_id)
