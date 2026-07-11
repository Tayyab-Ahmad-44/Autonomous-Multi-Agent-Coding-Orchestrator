import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.agents import FixPlannerAgent, PlannerAgent, SpecAgent, ValidatorAgent
from app.models import Mission, User
from app.orchestration.mission_graph import run_mission_orchestrator, run_mission_tick
from app.schemas import (
    FeatureTaskRead,
    MilestoneRead,
    MissionCreate,
    MissionDetailRead,
    MissionEventRead,
    MissionPlanRejection,
    MissionRead,
    MissionStatusUpdate,
    OpenPrResponse,
    RepoProfileRead,
    RepositoryCloneResponse,
    RepositoryCreate,
    RepositoryRead,
    ValidationContractRead,
    ValidationReportRead,
)
from app.core.config import get_settings
from app.services import missions as mission_service
from app.services.github_service import GitHubService, GitHubServiceError


router = APIRouter(prefix="/missions", tags=["missions"])


def _require_owned_mission(db: DbSession, mission_id: UUID, current_user: User) -> Mission:
    mission = mission_service.get_mission(db, mission_id)
    if mission is None or mission.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")
    return mission


def get_planner_agent() -> PlannerAgent:
    return PlannerAgent()


def get_spec_agent() -> SpecAgent:
    return SpecAgent()


def get_validator_agent() -> ValidatorAgent:
    return ValidatorAgent()


def get_fix_planner_agent() -> FixPlannerAgent:
    return FixPlannerAgent()


@router.post("", response_model=MissionRead, status_code=status.HTTP_201_CREATED)
def create_mission(payload: MissionCreate, current_user: CurrentUser, db: DbSession) -> MissionRead:
    try:
        return mission_service.create_mission(
            db,
            owner_id=current_user.id,
            repo_id=payload.repo_id,
            title=payload.title,
            goal=payload.goal,
        )
    except mission_service.RepoNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found") from None


@router.get("", response_model=list[MissionRead])
def list_missions(
    current_user: CurrentUser,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MissionRead]:
    return mission_service.list_missions(db, owner_id=current_user.id, offset=offset, limit=limit)


@router.get("/{mission_id}", response_model=MissionDetailRead)
def get_mission(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> MissionDetailRead:
    mission = mission_service.get_mission_with_details(db, mission_id)
    if mission is None or mission.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")

    return _to_mission_detail(mission)


@router.get("/{mission_id}/events")
async def mission_events(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> StreamingResponse:
    mission = mission_service.get_mission_with_details(db, mission_id)
    if mission is None or mission.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")

    return StreamingResponse(
        stream_mission_events(db, mission_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def stream_mission_events(db, mission_id: UUID, interval_seconds: float = 2.0):
    while True:
        db.expire_all()
        mission = mission_service.get_mission_with_details(db, mission_id)
        if mission is None:
            yield "event: mission_deleted\ndata: {}\n\n"
            return
        payload = _to_mission_detail(mission).model_dump_json()
        yield f"event: mission\ndata: {payload}\n\n"
        await asyncio.sleep(interval_seconds)


@router.post(
    "/{mission_id}/repository",
    response_model=RepositoryRead,
    status_code=status.HTTP_201_CREATED,
)
def set_repository(
    mission_id: UUID,
    payload: RepositoryCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> RepositoryRead:
    _require_owned_mission(db, mission_id, current_user)
    repository = mission_service.upsert_repository(
        db,
        mission_id=mission_id,
        provider=payload.provider,
        repo_url=payload.repo_url,
        default_branch=payload.default_branch,
        local_path=payload.local_path,
        github_owner=payload.github_owner,
        github_repo=payload.github_repo,
    )

    return RepositoryRead.model_validate(repository)


@router.get("/{mission_id}/repository", response_model=RepositoryRead)
def get_repository(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> RepositoryRead:
    _require_owned_mission(db, mission_id, current_user)

    repository = mission_service.get_repository(db, mission_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    return RepositoryRead.model_validate(repository)


@router.post(
    "/{mission_id}/repository/clone",
    response_model=RepositoryCloneResponse,
    status_code=status.HTTP_200_OK,
)
def clone_repository(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> RepositoryCloneResponse:
    _require_owned_mission(db, mission_id, current_user)
    try:
        result = mission_service.clone_mission_repository(db, mission_id=mission_id)
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    repo = result.repository
    return RepositoryCloneResponse(
        id=repo.id,
        mission_id=repo.mission_id,
        provider=repo.provider,
        repo_url=repo.repo_url,
        default_branch=repo.default_branch,
        local_path=repo.local_path,
        github_owner=repo.github_owner,
        github_repo=repo.github_repo,
        created_at=repo.created_at,
        current_branch=result.current_branch,
    )


@router.post("/{mission_id}/analyze-repo", response_model=RepoProfileRead, status_code=status.HTTP_200_OK)
def analyze_repo(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> RepoProfileRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        profile = mission_service.analyze_repo_for_mission(db, mission_id)
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Repository analysis failed: {exc}",
        ) from exc

    return RepoProfileRead.model_validate(profile)


@router.post("/{mission_id}/plan", response_model=MissionDetailRead)
async def plan_mission(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    planner_agent: PlannerAgent = Depends(get_planner_agent),
) -> MissionDetailRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        mission = await mission_service.run_planning_for_mission(
            db,
            mission_id,
            planner_agent=planner_agent,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mission planning failed: {exc}",
        ) from exc

    return _to_mission_detail(mission)


@router.post(
    "/{mission_id}/validation-contract",
    response_model=ValidationContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_validation_contract(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    spec_agent: SpecAgent = Depends(get_spec_agent),
) -> ValidationContractRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        contract = await mission_service.generate_validation_contract(
            db,
            mission_id,
            spec_agent=spec_agent,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation contract generation failed: {exc}",
        ) from exc

    return ValidationContractRead.model_validate(contract)


@router.post(
    "/{mission_id}/validate",
    response_model=ValidationReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def validate_mission(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    validator_agent: ValidatorAgent = Depends(get_validator_agent),
) -> ValidationReportRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        report = await mission_service.run_validation_for_mission(
            db,
            mission_id,
            validator_agent=validator_agent,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mission validation failed: {exc}",
        ) from exc

    return ValidationReportRead.model_validate(report)


@router.post("/{mission_id}/orchestrate", response_model=MissionDetailRead)
async def orchestrate_mission(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    planner_agent: PlannerAgent = Depends(get_planner_agent),
    spec_agent: SpecAgent = Depends(get_spec_agent),
) -> MissionDetailRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        state = await run_mission_orchestrator(
            db,
            mission_id,
            planner_agent=planner_agent,
            spec_agent=spec_agent,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mission orchestration failed: {exc}",
        ) from exc

    return _to_mission_detail(state["mission"])


@router.post("/{mission_id}/tick", response_model=MissionDetailRead)
async def tick_mission(
    mission_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    planner_agent: PlannerAgent = Depends(get_planner_agent),
    spec_agent: SpecAgent = Depends(get_spec_agent),
    validator_agent: ValidatorAgent = Depends(get_validator_agent),
    fix_planner_agent: FixPlannerAgent = Depends(get_fix_planner_agent),
) -> MissionDetailRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        state = await run_mission_tick(
            db,
            mission_id,
            planner_agent=planner_agent,
            spec_agent=spec_agent,
            validator_agent=validator_agent,
            fix_planner_agent=fix_planner_agent,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mission tick failed: {exc}",
        ) from exc

    return _to_mission_detail(state["mission"])


@router.post("/{mission_id}/approve-plan", response_model=MissionDetailRead)
def approve_plan(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> MissionDetailRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        mission = mission_service.approve_plan(db, mission_id)
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _to_mission_detail(mission)


@router.post("/{mission_id}/reject-plan", response_model=MissionDetailRead)
def reject_plan(
    mission_id: UUID,
    payload: MissionPlanRejection,
    current_user: CurrentUser,
    db: DbSession,
    reset: bool = Query(default=False),
) -> MissionDetailRead:
    _require_owned_mission(db, mission_id, current_user)
    try:
        mission = mission_service.reject_plan(
            db,
            mission_id,
            feedback=payload.feedback,
            reset=reset,
        )
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None

    return _to_mission_detail(mission)


def _to_mission_detail(mission: Mission) -> MissionDetailRead:
    latest_contract = max(
        mission.validation_contracts,
        key=lambda contract: contract.created_at,
        default=None,
    )

    return MissionDetailRead(
        id=mission.id,
        owner_id=mission.owner_id,
        repo_id=mission.repo_id,
        title=mission.title,
        goal=mission.goal,
        status=mission.status,
        current_milestone_id=mission.current_milestone_id,
        created_at=mission.created_at,
        updated_at=mission.updated_at,
        milestones=[
            MilestoneRead.model_validate(milestone)
            for milestone in sorted(mission.milestones, key=lambda item: item.order_index)
        ],
        feature_tasks=[
            FeatureTaskRead.model_validate(task)
            for task in sorted(mission.feature_tasks, key=lambda item: item.created_at)
        ],
        validation_contract=(
            ValidationContractRead.model_validate(latest_contract) if latest_contract else None
        ),
        validation_reports=[
            ValidationReportRead.model_validate(report)
            for report in sorted(
                mission.validation_reports,
                key=lambda item: item.created_at,
                reverse=True,
            )
        ],
        events=[
            MissionEventRead.model_validate(event)
            for event in sorted(
                mission.events,
                key=lambda item: item.created_at,
                reverse=True,
            )
        ],
        repo_profile=(
            RepoProfileRead.model_validate(mission.repo_profile)
            if hasattr(mission, "repo_profile") and mission.repo_profile is not None
            else None
        ),
    )


@router.patch("/{mission_id}/status", response_model=MissionRead)
def update_mission_status(
    mission_id: UUID,
    payload: MissionStatusUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> MissionRead:
    mission = _require_owned_mission(db, mission_id, current_user)

    return mission_service.set_mission_status(db, mission, payload.status)


@router.post("/{mission_id}/open-pr", response_model=OpenPrResponse)
def open_pr(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> OpenPrResponse:
    _require_owned_mission(db, mission_id, current_user)
    settings = get_settings()
    if not settings.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GITHUB_TOKEN is not configured on the server.",
        )

    github = GitHubService(token=settings.github_token)

    try:
        result = mission_service.open_mission_pr(db, mission_id=mission_id, github=github)
    except mission_service.MissionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found") from None
    except mission_service.MissionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return OpenPrResponse(pr_url=result.pr_url, branch=result.branch)


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mission(mission_id: UUID, current_user: CurrentUser, db: DbSession) -> Response:
    mission = _require_owned_mission(db, mission_id, current_user)

    mission_service.delete_mission(db, mission)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
