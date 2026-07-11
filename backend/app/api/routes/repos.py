from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import RepoCreate, RepoRead
from app.services import repos as repo_service


router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("", response_model=RepoRead, status_code=status.HTTP_201_CREATED)
def create_repo(payload: RepoCreate, current_user: CurrentUser, db: DbSession) -> RepoRead:
    try:
        return repo_service.create_repo(
            db,
            user_id=current_user.id,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
        )
    except repo_service.RepoAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[RepoRead])
def list_repos(
    current_user: CurrentUser,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RepoRead]:
    return repo_service.list_repos(db, user_id=current_user.id, offset=offset, limit=limit)
