from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.agents import AgentContext, AgentInput, FixPlannerAgent, PlannerAgent, SpecAgent, ValidatorAgent
from app.core.config import get_settings
from app.services.git_service import GitService, GitServiceError
from app.services.github_service import GitHubService, GitHubServiceError
from app.models import (
    AgentRun,
    AgentRunStatus,
    Artifact,
    FeatureTask,
    FeatureTaskStatus,
    FeatureTaskType,
    Milestone,
    MissionDecision,
    MissionEvent,
    MilestoneStatus,
    Mission,
    MissionStatus,
    RepoProfile,
    Repository,
    RepositoryProvider,
    ValidationContract,
    ValidationReport,
)


JsonObject = dict[str, Any]
JsonList = list[dict[str, Any]]


class MissionNotFoundError(ValueError):
    pass


class MissionNotReadyError(ValueError):
    pass


def create_mission(db: Session, *, title: str, goal: str) -> Mission:
    mission = Mission(title=title, goal=goal, status=MissionStatus.draft)
    db.add(mission)
    db.commit()
    db.refresh(mission)
    log_mission_event(
        db,
        mission_id=mission.id,
        event_type="mission_created",
        message=f"Mission created: {mission.title}",
        payload={"title": mission.title},
    )
    return mission


def get_mission(db: Session, mission_id: UUID) -> Mission | None:
    return db.get(Mission, mission_id)


def get_agent_run(db: Session, agent_run_id: UUID) -> AgentRun | None:
    return db.get(AgentRun, agent_run_id)


def get_feature_task(db: Session, feature_task_id: UUID) -> FeatureTask | None:
    return db.get(FeatureTask, feature_task_id)


def get_repository(db: Session, mission_id: UUID) -> Repository | None:
    statement = select(Repository).where(Repository.mission_id == mission_id)
    return db.scalars(statement).first()


def get_repo_profile(db: Session, mission_id: UUID) -> RepoProfile | None:
    statement = select(RepoProfile).where(RepoProfile.mission_id == mission_id)
    return db.scalars(statement).first()


def save_repo_profile(
    db: Session,
    *,
    mission_id: UUID,
    frontend_framework: str | None,
    backend_framework: str | None,
    package_manager: str | None,
    language: str | None,
    test_commands: list[str],
    build_commands: list[str],
    important_dirs: list[str],
    has_docker: bool,
    has_ci: bool,
    readme_summary: str | None,
    raw_data: dict,
) -> RepoProfile:
    profile = get_repo_profile(db, mission_id)
    if profile is None:
        profile = RepoProfile(mission_id=mission_id)
        db.add(profile)

    profile.frontend_framework = frontend_framework
    profile.backend_framework = backend_framework
    profile.package_manager = package_manager
    profile.language = language
    profile.test_commands = test_commands
    profile.build_commands = build_commands
    profile.important_dirs = important_dirs
    profile.has_docker = has_docker
    profile.has_ci = has_ci
    profile.readme_summary = readme_summary
    profile.raw_data = raw_data

    db.commit()
    db.refresh(profile)
    return profile


def get_latest_validation_contract(db: Session, mission_id: UUID) -> ValidationContract | None:
    statement = (
        select(ValidationContract)
        .where(ValidationContract.mission_id == mission_id)
        .order_by(ValidationContract.created_at.desc())
        .limit(1)
    )
    return db.scalars(statement).first()


def get_mission_with_details(db: Session, mission_id: UUID) -> Mission | None:
    statement = (
        select(Mission)
        .options(
            selectinload(Mission.milestones),
            selectinload(Mission.feature_tasks),
            selectinload(Mission.validation_contracts),
            selectinload(Mission.validation_reports),
            selectinload(Mission.repository),
            selectinload(Mission.events),
            selectinload(Mission.agent_runs),
            selectinload(Mission.repo_profile),
        )
        .where(Mission.id == mission_id)
    )
    return db.scalars(statement).first()


def get_mission_for_spec(db: Session, mission_id: UUID) -> Mission | None:
    statement = (
        select(Mission)
        .options(
            selectinload(Mission.milestones),
            selectinload(Mission.feature_tasks),
        )
        .where(Mission.id == mission_id)
    )
    return db.scalars(statement).first()


def list_missions(db: Session, *, offset: int = 0, limit: int = 100) -> list[Mission]:
    statement = select(Mission).order_by(Mission.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(statement).all())


def log_mission_event(
    db: Session,
    *,
    mission_id: UUID,
    event_type: str,
    message: str,
    payload: JsonObject | None = None,
) -> MissionEvent:
    event = MissionEvent(
        mission_id=mission_id,
        event_type=event_type,
        message=message,
        payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def set_mission_status(db: Session, mission: Mission, status: MissionStatus) -> Mission:
    previous_status = mission.status
    mission.status = status
    db.add(mission)
    db.commit()
    db.refresh(mission)
    if status == MissionStatus.completed and previous_status != MissionStatus.completed:
        log_mission_event(
            db,
            mission_id=mission.id,
            event_type="mission_completed",
            message="Mission completed.",
            payload={"mission_id": str(mission.id)},
        )
    return mission


def delete_mission(db: Session, mission: Mission) -> None:
    db.delete(mission)
    db.commit()


def upsert_repository(
    db: Session,
    *,
    mission_id: UUID,
    provider: RepositoryProvider,
    repo_url: str,
    default_branch: str = "main",
    local_path: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
) -> Repository:
    mission = get_mission(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    repository = get_repository(db, mission_id)
    if repository is None:
        repository = Repository(
            mission_id=mission_id,
            provider=provider,
            repo_url=repo_url,
            default_branch=default_branch,
            local_path=local_path,
            github_owner=github_owner,
            github_repo=github_repo,
        )
    else:
        repository.provider = provider
        repository.repo_url = repo_url
        repository.default_branch = default_branch
        repository.local_path = local_path
        repository.github_owner = github_owner
        repository.github_repo = github_repo

    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@dataclass
class CloneResult:
    repository: Repository
    current_branch: str


def clone_mission_repository(
    db: Session,
    *,
    mission_id: UUID,
    repo_url: str,
    default_branch: str = "main",
    git: GitService | None = None,
) -> CloneResult:
    mission = get_mission(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    settings = get_settings()
    workspace_path = Path(settings.workspace_root) / "missions" / str(mission_id) / "repo"
    workspace_str = str(workspace_path)

    git_svc = git or GitService()

    try:
        if workspace_path.exists() and git_svc.is_git_repo(workspace_str):
            git_svc.fetch(workspace_str)
        else:
            git_svc.clone_repo(repo_url, workspace_str)

        git_svc.checkout(workspace_str, default_branch)
        git_svc.pull(workspace_str)

        mission_branch = f"mission/{str(mission_id)[:8]}"
        git_svc.create_or_checkout_branch(workspace_str, mission_branch)
        current_branch = git_svc.current_branch(workspace_str)
    except GitServiceError as exc:
        raise RuntimeError(f"Git operation failed: {exc}") from exc

    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", repo_url)
    if match:
        provider = RepositoryProvider.github
        github_owner: str | None = match.group(1)
        github_repo: str | None = match.group(2)
    else:
        provider = RepositoryProvider.local
        github_owner = None
        github_repo = None

    repository = upsert_repository(
        db,
        mission_id=mission_id,
        provider=provider,
        repo_url=repo_url,
        default_branch=default_branch,
        local_path=workspace_str,
        github_owner=github_owner,
        github_repo=github_repo,
    )

    log_mission_event(
        db,
        mission_id=mission_id,
        event_type="repository_cloned",
        message=f"Repository ready at {workspace_str} on branch {current_branch}",
        payload={"repo_url": repo_url, "local_path": workspace_str, "branch": current_branch},
    )

    return CloneResult(repository=repository, current_branch=current_branch)


def analyze_repo_for_mission(db: Session, mission_id: UUID) -> RepoProfile:
    from app.services.repo_analysis_service import RepoAnalysisService

    mission = get_mission(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    repository = get_repository(db, mission_id)
    if repository is None or not repository.local_path:
        raise MissionNotReadyError(
            "Repository must be cloned before running analysis. "
            "Clone the repository first."
        )

    local_path = repository.local_path
    svc = RepoAnalysisService()
    data = svc.analyze_repo(local_path)

    profile = save_repo_profile(
        db,
        mission_id=mission_id,
        frontend_framework=data.frontend_framework,
        backend_framework=data.backend_framework,
        package_manager=data.package_manager,
        language=data.language,
        test_commands=data.test_commands,
        build_commands=data.build_commands,
        important_dirs=data.important_dirs,
        has_docker=data.has_docker,
        has_ci=data.has_ci,
        readme_summary=data.readme_summary,
        raw_data=data.raw_data,
    )

    log_mission_event(
        db,
        mission_id=mission_id,
        event_type="repo_analyzed",
        message="Repository analysis complete.",
        payload={
            "frontend_framework": data.frontend_framework,
            "backend_framework": data.backend_framework,
            "language": data.language,
            "important_dirs": data.important_dirs,
        },
    )

    return profile


def create_milestone(
    db: Session,
    *,
    mission_id: UUID,
    name: str,
    description: str,
    order_index: int,
    status: MilestoneStatus = MilestoneStatus.pending,
) -> Milestone:
    milestone = Milestone(
        mission_id=mission_id,
        name=name,
        description=description,
        order_index=order_index,
        status=status,
    )
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def create_feature_task(
    db: Session,
    *,
    mission_id: UUID,
    title: str,
    description: str,
    task_type: FeatureTaskType,
    milestone_id: UUID | None = None,
    assigned_agent_type: str | None = None,
    depends_on: list[str] | None = None,
) -> FeatureTask:
    task = FeatureTask(
        mission_id=mission_id,
        milestone_id=milestone_id,
        title=title,
        description=description,
        task_type=task_type,
        status=FeatureTaskStatus.pending,
        assigned_agent_type=assigned_agent_type,
        depends_on=depends_on,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def set_feature_task_status(
    db: Session,
    feature_task: FeatureTask,
    status: FeatureTaskStatus,
) -> FeatureTask:
    feature_task.status = status
    db.add(feature_task)
    db.commit()
    db.refresh(feature_task)
    return feature_task


def set_milestone_status(
    db: Session,
    milestone: Milestone,
    status: MilestoneStatus,
) -> Milestone:
    milestone.status = status
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def create_agent_run_for_feature_task(db: Session, feature_task: FeatureTask) -> AgentRun:
    agent_type = feature_task.assigned_agent_type or _agent_type_for_task_type(feature_task.task_type)
    agent_run = create_agent_run(
        db,
        mission_id=feature_task.mission_id,
        feature_task_id=feature_task.id,
        agent_type=agent_type,
        input={
            "instructions": feature_task.description,
            "data": {
                "feature_task_id": str(feature_task.id),
                "mission_id": str(feature_task.mission_id),
                "milestone_id": str(feature_task.milestone_id) if feature_task.milestone_id else None,
                "title": feature_task.title,
                "description": feature_task.description,
                "task_type": feature_task.task_type.value,
                "depends_on": feature_task.depends_on or [],
            },
        },
    )
    log_mission_event(
        db,
        mission_id=feature_task.mission_id,
        event_type="task_queued",
        message=f"Queued task: {feature_task.title}",
        payload={
            "feature_task_id": str(feature_task.id),
            "agent_run_id": str(agent_run.id),
            "agent_type": agent_type,
            "task_type": feature_task.task_type.value,
        },
    )
    return agent_run


def create_worker_agent_run_for_feature_task(db: Session, feature_task: FeatureTask) -> AgentRun:
    agent_run = _create_feature_task_agent_run(db, feature_task, agent_type="worker")
    log_mission_event(
        db,
        mission_id=feature_task.mission_id,
        event_type="task_queued",
        message=f"Queued worker task: {feature_task.title}",
        payload={
            "feature_task_id": str(feature_task.id),
            "agent_run_id": str(agent_run.id),
            "agent_type": "worker",
            "task_type": feature_task.task_type.value,
        },
    )
    return agent_run


def _create_feature_task_agent_run(
    db: Session,
    feature_task: FeatureTask,
    *,
    agent_type: str,
) -> AgentRun:
    return create_agent_run(
        db,
        mission_id=feature_task.mission_id,
        feature_task_id=feature_task.id,
        agent_type=agent_type,
        input={
            "instructions": feature_task.description,
            "data": {
                "feature_task_id": str(feature_task.id),
                "mission_id": str(feature_task.mission_id),
                "milestone_id": str(feature_task.milestone_id) if feature_task.milestone_id else None,
                "title": feature_task.title,
                "description": feature_task.description,
                "task_type": feature_task.task_type.value,
                "depends_on": feature_task.depends_on or [],
            },
        },
    )


def _agent_type_for_task_type(task_type: FeatureTaskType) -> str:
    if task_type == FeatureTaskType.research:
        return "research"
    if task_type == FeatureTaskType.fix:
        return "worker"
    return "worker"


async def run_planning_for_mission(
    db: Session,
    mission_id: UUID,
    planner_agent: PlannerAgent | None = None,
) -> Mission:
    mission = get_mission(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    mission = set_mission_status(db, mission, MissionStatus.planning)

    # Auto-analyze repo if cloned but not yet profiled.
    repo_profile = get_repo_profile(db, mission_id)
    if repo_profile is None:
        repository = get_repository(db, mission_id)
        if repository is not None and repository.local_path:
            try:
                repo_profile = analyze_repo_for_mission(db, mission_id)
            except Exception:
                repo_profile = None

    mission_decisions = list_mission_decisions(db, mission_id)
    agent_input = AgentInput(
        instructions="Create an MVP implementation plan for this mission.",
        data={
            "title": mission.title,
            "goal": mission.goal,
            "repo_profile": _repo_profile_to_dict(repo_profile),
            "mission_decisions": _mission_decisions_to_dicts(mission_decisions),
        },
    )
    agent_run = create_agent_run(
        db,
        mission_id=mission.id,
        agent_type=PlannerAgent.agent_type,
        input={
            "instructions": agent_input.instructions,
            "data": agent_input.data,
        },
    )

    try:
        mark_agent_run_running(db, agent_run)
        agent = planner_agent or PlannerAgent()
        output = await agent.run(
            AgentContext(mission_id=mission.id, db=db),
            agent_input,
        )
        _persist_plan(db, mission_id=mission.id, plan=output.data)
        complete_agent_run(
            db,
            agent_run,
            output={
                "status": output.status,
                "summary": output.summary,
                "data": output.data,
            },
        )
        log_mission_event(
            db,
            mission_id=mission.id,
            event_type="plan_generated",
            message="Plan generated.",
            payload={
                "agent_run_id": str(agent_run.id),
                "milestones": len(output.data.get("milestones", [])),
            },
        )
        mission = set_mission_status(db, mission, MissionStatus.waiting_for_approval)
    except Exception as exc:
        complete_agent_run(db, agent_run, error=str(exc))
        set_mission_status(db, mission, MissionStatus.failed)
        raise

    planned_mission = get_mission_with_details(db, mission.id)
    if planned_mission is None:
        raise MissionNotFoundError(f"Mission not found after planning: {mission_id}")
    return planned_mission


def _repo_profile_to_dict(profile: RepoProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "frontend_framework": profile.frontend_framework,
        "backend_framework": profile.backend_framework,
        "package_manager": profile.package_manager,
        "language": profile.language,
        "test_commands": profile.test_commands,
        "build_commands": profile.build_commands,
        "important_dirs": profile.important_dirs,
        "has_docker": profile.has_docker,
        "has_ci": profile.has_ci,
        "readme_summary": profile.readme_summary,
    }


def _mission_decisions_to_dicts(decisions: list[MissionDecision]) -> list[JsonObject]:
    return [{"key": decision.key, "value": decision.value} for decision in decisions]


def _persist_plan(db: Session, *, mission_id: UUID, plan: JsonObject) -> None:
    for milestone_data in sorted(
        plan["milestones"],
        key=lambda item: item.get("order_index", 0),
    ):
        milestone = create_milestone(
            db,
            mission_id=mission_id,
            name=milestone_data["name"],
            description=milestone_data["description"],
            order_index=milestone_data["order_index"],
        )
        for feature_data in milestone_data["features"]:
            create_feature_task(
                db,
                mission_id=mission_id,
                milestone_id=milestone.id,
                title=feature_data["title"],
                description=feature_data["description"],
                task_type=FeatureTaskType(feature_data["task_type"]),
                assigned_agent_type=_assigned_agent_type(feature_data["task_type"]),
            )


def _assigned_agent_type(task_type: str) -> str:
    if task_type == FeatureTaskType.research.value:
        return "research"
    if task_type == FeatureTaskType.docs.value:
        return "worker"
    return "worker"


def approve_plan(db: Session, mission_id: UUID) -> Mission:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")
    if not mission.milestones or not mission.feature_tasks or not mission.validation_contracts:
        raise MissionNotReadyError(
            "Mission requires milestones, feature tasks, and a validation contract before approval."
        )

    first_milestone = min(mission.milestones, key=lambda item: item.order_index)
    mission.status = MissionStatus.running
    mission.current_milestone_id = first_milestone.id
    first_milestone.status = MilestoneStatus.running

    for task in mission.feature_tasks:
        if task.milestone_id == first_milestone.id:
            task.status = FeatureTaskStatus.pending

    db.add(mission)
    db.add(first_milestone)
    db.commit()

    approved_mission = get_mission_with_details(db, mission_id)
    if approved_mission is None:
        raise MissionNotFoundError(f"Mission not found after approval: {mission_id}")
    return approved_mission


def reject_plan(
    db: Session,
    mission_id: UUID,
    *,
    feedback: str,
    reset: bool = False,
) -> Mission:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    agent_run = create_agent_run(
        db,
        mission_id=mission.id,
        agent_type="human_feedback",
        input={
            "action": "reject_plan",
            "reset": reset,
        },
    )
    complete_agent_run(
        db,
        agent_run,
        output={
            "feedback": feedback,
            "reset": reset,
        },
    )

    mission.status = MissionStatus.draft
    mission.current_milestone_id = None
    db.add(mission)
    db.commit()

    if reset:
        _reset_plan_artifacts(db, mission.id)

    rejected_mission = get_mission_with_details(db, mission_id)
    if rejected_mission is None:
        raise MissionNotFoundError(f"Mission not found after rejection: {mission_id}")
    return rejected_mission


def _reset_plan_artifacts(db: Session, mission_id: UUID) -> None:
    db.execute(
        update(AgentRun)
        .where(AgentRun.mission_id == mission_id)
        .values(feature_task_id=None)
    )
    db.execute(delete(ValidationReport).where(ValidationReport.mission_id == mission_id))
    db.execute(delete(ValidationContract).where(ValidationContract.mission_id == mission_id))
    db.execute(delete(FeatureTask).where(FeatureTask.mission_id == mission_id))
    db.execute(delete(Milestone).where(Milestone.mission_id == mission_id))
    db.commit()


async def generate_validation_contract(
    db: Session,
    mission_id: UUID,
    spec_agent: SpecAgent | None = None,
) -> ValidationContract:
    mission = get_mission_for_spec(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")
    if not mission.milestones or not mission.feature_tasks:
        raise MissionNotReadyError(
            "Mission must have generated milestones and feature tasks before creating a validation contract."
        )

    agent_input = AgentInput(
        instructions="Create a validation contract for this mission.",
        data={
            "goal": mission.goal,
            "milestones": _milestones_for_agent(mission.milestones),
            "feature_tasks": _feature_tasks_for_agent(mission.feature_tasks),
        },
    )
    agent_run = create_agent_run(
        db,
        mission_id=mission.id,
        agent_type=SpecAgent.agent_type,
        input={
            "instructions": agent_input.instructions,
            "data": agent_input.data,
        },
    )

    try:
        mark_agent_run_running(db, agent_run)
        agent = spec_agent or SpecAgent()
        output = await agent.run(
            AgentContext(mission_id=mission.id, db=db),
            agent_input,
        )
        contract = create_validation_contract(
            db,
            mission_id=mission.id,
            content=output.data["contract_markdown"],
            assertions=output.data["assertions"],
            required_tests=output.data["required_tests"],
        )
        complete_agent_run(
            db,
            agent_run,
            output={
                "status": output.status,
                "summary": output.summary,
                "data": output.data,
            },
        )
        log_mission_event(
            db,
            mission_id=mission.id,
            event_type="validation_contract_generated",
            message="Validation contract generated.",
            payload={
                "agent_run_id": str(agent_run.id),
                "validation_contract_id": str(contract.id),
                "assertions": len(contract.assertions),
                "required_tests": len(contract.required_tests),
            },
        )
        set_mission_status(db, mission, MissionStatus.waiting_for_approval)
    except Exception as exc:
        complete_agent_run(db, agent_run, error=str(exc))
        set_mission_status(db, mission, MissionStatus.failed)
        raise

    return contract


async def run_validation_for_mission(
    db: Session,
    mission_id: UUID,
    validator_agent: ValidatorAgent | None = None,
) -> ValidationReport:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")
    if mission.repository is None or not mission.repository.local_path:
        raise MissionNotReadyError("Mission requires a local repository before validation.")

    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        raise MissionNotReadyError("Mission requires at least one milestone before validation.")

    contract = _latest_validation_contract_from_mission(mission)
    if contract is None:
        raise MissionNotReadyError("Mission requires a validation contract before validation.")

    agent_input = AgentInput(
        instructions="Run validation contract tests for this mission.",
        data={
            "mission": _mission_for_agent(mission),
            "milestone": _milestone_for_agent(milestone),
            "validation_contract": _validation_contract_for_agent(contract),
            "repo_path": mission.repository.local_path,
        },
    )
    agent_run = create_agent_run(
        db,
        mission_id=mission.id,
        agent_type=ValidatorAgent.agent_type,
        input={
            "instructions": agent_input.instructions,
            "data": agent_input.data,
        },
    )

    try:
        mark_agent_run_running(db, agent_run)
        agent = validator_agent or ValidatorAgent()
        output = await agent.run(
            AgentContext(
                mission_id=mission.id,
                agent_run_id=agent_run.id,
                db=db,
                repo_path=Path(mission.repository.local_path),
            ),
            agent_input,
        )
        complete_agent_run(
            db,
            agent_run,
            output={
                "status": output.status,
                "summary": output.summary,
                "data": output.data,
            },
        )
    except Exception as exc:
        complete_agent_run(db, agent_run, error=str(exc))
        raise

    report_id = output.data.get("validation_report_id")
    if report_id:
        report = db.get(ValidationReport, UUID(str(report_id)))
        if report is not None:
            return report

    statement = (
        select(ValidationReport)
        .where(ValidationReport.mission_id == mission.id)
        .order_by(ValidationReport.created_at.desc())
        .limit(1)
    )
    report = db.scalars(statement).first()
    if report is None:
        raise ValueError("ValidatorAgent completed without creating a ValidationReport.")
    return report


async def create_fix_tasks_from_validation_report(
    db: Session,
    report_id: UUID,
    fix_planner_agent: FixPlannerAgent | None = None,
) -> Mission:
    validation_report = db.get(ValidationReport, report_id)
    if validation_report is None:
        raise MissionNotFoundError(f"ValidationReport not found: {report_id}")
    if validation_report.passed:
        raise MissionNotReadyError("Fix tasks can only be created from failed validation reports.")

    mission = get_mission_with_details(db, validation_report.mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {validation_report.mission_id}")

    milestone = _milestone_for_report_or_current(mission, validation_report)
    if milestone is None:
        raise MissionNotReadyError("Mission requires a milestone before fix tasks can be planned.")

    validation_contract = _latest_validation_contract_from_mission(mission)
    if validation_contract is None:
        raise MissionNotReadyError("Mission requires a validation contract before fix tasks can be planned.")

    agent_input = AgentInput(
        instructions="Create fix tasks for the failed validation report.",
        data={
            "mission_goal": mission.goal,
            "validation_contract": _validation_contract_for_agent(validation_contract),
            "failed_milestone": _milestone_for_agent(milestone),
            "validation_report": _validation_report_for_agent(validation_report),
        },
    )
    agent_run = create_agent_run(
        db,
        mission_id=mission.id,
        agent_type=FixPlannerAgent.agent_type,
        input={
            "instructions": agent_input.instructions,
            "data": agent_input.data,
        },
    )

    try:
        mark_agent_run_running(db, agent_run)
        agent = fix_planner_agent or FixPlannerAgent()
        output = await agent.run(
            AgentContext(
                mission_id=mission.id,
                agent_run_id=agent_run.id,
                db=db,
            ),
            agent_input,
        )
        fix_tasks = _fix_tasks_from_output(output.data)
        for task_data in fix_tasks:
            create_feature_task(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                title=task_data["title"],
                description=task_data["description"],
                task_type=FeatureTaskType.fix,
                assigned_agent_type=task_data["assigned_agent_type"],
            )
        fix_task_count = len(fix_tasks)
        _set_mission_and_milestone_statuses(
            db,
            mission=mission,
            milestone=milestone,
            mission_status=MissionStatus.running,
            milestone_status=MilestoneStatus.running,
        )
        complete_agent_run(
            db,
            agent_run,
            output={
                "status": output.status,
                "summary": output.summary,
                "data": output.data,
            },
        )
        log_mission_event(
            db,
            mission_id=mission.id,
            event_type="fix_tasks_created",
            message=f"Created {fix_task_count} fix task(s).",
            payload={
                "agent_run_id": str(agent_run.id),
                "validation_report_id": str(validation_report.id),
                "milestone_id": str(milestone.id),
                "fix_task_count": fix_task_count,
            },
        )
    except Exception as exc:
        complete_agent_run(db, agent_run, error=str(exc))
        raise

    refreshed = get_mission_with_details(db, mission.id)
    if refreshed is None:
        raise MissionNotFoundError(f"Mission not found after fix planning: {mission.id}")
    return refreshed


def get_current_or_first_milestone(mission: Mission) -> Milestone | None:
    return _current_or_first_milestone(mission)


def get_next_pending_feature_task_in_current_milestone(mission: Mission) -> FeatureTask | None:
    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        return None
    pending_tasks = [
        task
        for task in mission.feature_tasks
        if task.milestone_id == milestone.id and task.status == FeatureTaskStatus.pending
    ]
    return min(pending_tasks, key=lambda task: task.created_at, default=None)


def current_milestone_has_running_tasks(mission: Mission) -> bool:
    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        return False
    return any(
        task.milestone_id == milestone.id and task.status == FeatureTaskStatus.running
        for task in mission.feature_tasks
    )


def get_active_agent_runs(mission: Mission) -> list[AgentRun]:
    return [
        run
        for run in mission.agent_runs
        if run.status in {AgentRunStatus.queued, AgentRunStatus.running}
    ]


def mission_has_active_agent_runs(mission: Mission) -> bool:
    return bool(get_active_agent_runs(mission))


def feature_task_has_active_agent_run(mission: Mission, feature_task_id: UUID) -> bool:
    return get_active_agent_run_for_feature_task(mission, feature_task_id) is not None


def get_active_agent_run_for_feature_task(mission: Mission, feature_task_id: UUID) -> AgentRun | None:
    active_runs = [
        run
        for run in mission.agent_runs
        if run.feature_task_id == feature_task_id
        and run.status in {AgentRunStatus.queued, AgentRunStatus.running}
    ]
    return min(active_runs, key=lambda run: run.created_at, default=None)


def get_failed_feature_task_in_current_milestone(mission: Mission) -> FeatureTask | None:
    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        return None
    failed_tasks = [
        task
        for task in mission.feature_tasks
        if task.milestone_id == milestone.id and task.status == FeatureTaskStatus.failed
    ]
    return min(failed_tasks, key=lambda task: task.created_at, default=None)


def count_failed_agent_runs_for_feature_task(mission: Mission, feature_task_id: UUID) -> int:
    return sum(
        1
        for run in mission.agent_runs
        if run.feature_task_id == feature_task_id and run.status == AgentRunStatus.failed
    )


def count_failed_validation_reports_for_milestone(
    db: Session,
    *,
    mission_id: UUID,
    milestone_id: UUID | None,
) -> int:
    statement = select(ValidationReport).where(
        ValidationReport.mission_id == mission_id,
        ValidationReport.passed.is_(False),
    )
    if milestone_id is None:
        statement = statement.where(ValidationReport.milestone_id.is_(None))
    else:
        statement = statement.where(ValidationReport.milestone_id == milestone_id)
    return len(db.scalars(statement).all())


def reconcile_current_milestone_task_statuses(db: Session, mission_id: UUID) -> Mission:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        return mission

    changed = False
    for task in mission.feature_tasks:
        if task.milestone_id != milestone.id or task.status != FeatureTaskStatus.running:
            continue
        if feature_task_has_active_agent_run(mission, task.id):
            continue

        latest_run = _latest_agent_run_for_feature_task(mission, task.id)
        if latest_run is None:
            task.status = FeatureTaskStatus.failed
            changed = True
            continue
        if latest_run.status == AgentRunStatus.failed:
            task.status = FeatureTaskStatus.failed
            changed = True
        elif latest_run.status == AgentRunStatus.completed:
            task.status = FeatureTaskStatus.completed
            changed = True

    if not changed:
        return mission

    db.commit()
    refreshed = get_mission_with_details(db, mission_id)
    if refreshed is None:
        raise MissionNotFoundError(f"Mission not found after task status reconciliation: {mission_id}")
    return refreshed


def _latest_agent_run_for_feature_task(mission: Mission, feature_task_id: UUID) -> AgentRun | None:
    runs = [run for run in mission.agent_runs if run.feature_task_id == feature_task_id]
    return max(runs, key=lambda run: run.created_at, default=None)


def current_milestone_tasks_are_completed(mission: Mission) -> bool:
    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        return False
    tasks = [task for task in mission.feature_tasks if task.milestone_id == milestone.id]
    return all(task.status == FeatureTaskStatus.completed for task in tasks)


def fail_mission_for_intervention(
    db: Session,
    mission: Mission,
    *,
    message: str,
    payload: JsonObject | None = None,
) -> Mission:
    milestone = _current_or_first_milestone(mission)
    mission.status = MissionStatus.failed
    if milestone is not None:
        milestone.status = MilestoneStatus.failed
        db.add(milestone)
    db.add(mission)
    db.commit()
    db.refresh(mission)
    log_mission_event(
        db,
        mission_id=mission.id,
        event_type="mission_failed",
        message=message,
        payload=payload,
    )
    refreshed = get_mission_with_details(db, mission.id)
    if refreshed is None:
        raise MissionNotFoundError(f"Mission not found after failure: {mission.id}")
    return refreshed


def mark_current_milestone_validating(db: Session, mission_id: UUID) -> Mission:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")
    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        raise MissionNotReadyError("Mission requires a milestone before validation.")

    _set_mission_and_milestone_statuses(
        db,
        mission=mission,
        milestone=milestone,
        mission_status=MissionStatus.validating,
        milestone_status=MilestoneStatus.validating,
    )
    refreshed = get_mission_with_details(db, mission_id)
    if refreshed is None:
        raise MissionNotFoundError(f"Mission not found after status update: {mission_id}")
    return refreshed


def advance_after_passed_validation(db: Session, mission_id: UUID) -> Mission:
    mission = get_mission_with_details(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    milestone = _current_or_first_milestone(mission)
    if milestone is None:
        raise MissionNotReadyError("Mission requires a milestone before it can advance.")

    next_milestone = _next_milestone_after(mission, milestone)
    milestone.status = MilestoneStatus.completed
    if next_milestone is None:
        mission.status = MissionStatus.completed
        mission.current_milestone_id = None
    else:
        mission.status = MissionStatus.running
        mission.current_milestone_id = next_milestone.id
        next_milestone.status = MilestoneStatus.running
        db.add(next_milestone)

    db.add(mission)
    db.add(milestone)
    db.commit()
    log_mission_event(
        db,
        mission_id=mission.id,
        event_type="milestone_completed",
        message=f"Milestone completed: {milestone.name}",
        payload={"milestone_id": str(milestone.id), "name": milestone.name},
    )
    if next_milestone is None:
        log_mission_event(
            db,
            mission_id=mission.id,
            event_type="mission_completed",
            message="Mission completed.",
            payload={"mission_id": str(mission.id)},
        )

    refreshed = get_mission_with_details(db, mission_id)
    if refreshed is None:
        raise MissionNotFoundError(f"Mission not found after milestone advance: {mission_id}")
    return refreshed


def _milestones_for_agent(milestones: list[Milestone]) -> list[JsonObject]:
    return [
        _milestone_for_agent(milestone)
        for milestone in sorted(milestones, key=lambda item: item.order_index)
    ]


def _mission_for_agent(mission: Mission) -> JsonObject:
    return {
        "id": str(mission.id),
        "title": mission.title,
        "goal": mission.goal,
        "status": mission.status.value,
        "current_milestone_id": (
            str(mission.current_milestone_id) if mission.current_milestone_id else None
        ),
    }


def _milestone_for_agent(milestone: Milestone) -> JsonObject:
    return {
        "id": str(milestone.id),
        "name": milestone.name,
        "description": milestone.description,
        "order_index": milestone.order_index,
        "status": milestone.status.value,
    }


def _feature_tasks_for_agent(feature_tasks: list[FeatureTask]) -> list[JsonObject]:
    return [
        {
            "id": str(task.id),
            "milestone_id": str(task.milestone_id) if task.milestone_id else None,
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type.value,
            "status": task.status.value,
        }
        for task in sorted(feature_tasks, key=lambda item: item.created_at)
    ]


def _validation_contract_for_agent(contract: ValidationContract) -> JsonObject:
    return {
        "id": str(contract.id),
        "content": contract.content,
        "assertions": contract.assertions,
        "required_tests": contract.required_tests,
    }


def _validation_report_for_agent(report: ValidationReport) -> JsonObject:
    return {
        "id": str(report.id),
        "mission_id": str(report.mission_id),
        "milestone_id": str(report.milestone_id) if report.milestone_id else None,
        "validator_type": report.validator_type,
        "passed": report.passed,
        "summary": report.summary,
        "issues": report.issues,
        "raw_output": report.raw_output,
    }


def _fix_tasks_from_output(output_data: JsonObject) -> JsonList:
    fix_tasks = output_data.get("fix_tasks", [])
    if not isinstance(fix_tasks, list):
        raise ValueError("FixPlannerAgent output must include fix_tasks as a list.")

    normalized: JsonList = []
    for index, task_data in enumerate(fix_tasks, start=1):
        if not isinstance(task_data, dict):
            continue
        title = str(task_data.get("title") or f"Fix validation issue {index}").strip()
        description = str(task_data.get("description") or "Repair failed validation.").strip()
        normalized.append(
            {
                "title": title[:255],
                "description": description,
                "task_type": FeatureTaskType.fix.value,
                "assigned_agent_type": "worker",
            }
        )
    if not normalized:
        normalized.append(
            {
                "title": "Investigate failed validation",
                "description": "Inspect the failed validation report and repair the failing behavior.",
                "task_type": FeatureTaskType.fix.value,
                "assigned_agent_type": "worker",
            }
        )
    return normalized


def _latest_validation_contract_from_mission(mission: Mission) -> ValidationContract | None:
    return max(
        mission.validation_contracts,
        key=lambda contract: contract.created_at,
        default=None,
    )


def _current_or_first_milestone(mission: Mission) -> Milestone | None:
    if mission.current_milestone_id:
        for milestone in mission.milestones:
            if milestone.id == mission.current_milestone_id:
                return milestone
    return min(mission.milestones, key=lambda milestone: milestone.order_index, default=None)


def _milestone_for_report_or_current(
    mission: Mission,
    validation_report: ValidationReport,
) -> Milestone | None:
    if validation_report.milestone_id:
        for milestone in mission.milestones:
            if milestone.id == validation_report.milestone_id:
                return milestone
    return _current_or_first_milestone(mission)


def _next_milestone_after(mission: Mission, current_milestone: Milestone) -> Milestone | None:
    later_milestones = [
        milestone
        for milestone in mission.milestones
        if milestone.order_index > current_milestone.order_index
    ]
    return min(later_milestones, key=lambda milestone: milestone.order_index, default=None)


def _set_mission_and_milestone_statuses(
    db: Session,
    *,
    mission: Mission,
    milestone: Milestone,
    mission_status: MissionStatus,
    milestone_status: MilestoneStatus,
) -> None:
    mission.status = mission_status
    milestone.status = milestone_status
    db.add(mission)
    db.add(milestone)
    db.commit()


def create_validation_contract(
    db: Session,
    *,
    mission_id: UUID,
    content: str,
    assertions: JsonList,
    required_tests: JsonList,
) -> ValidationContract:
    contract = ValidationContract(
        mission_id=mission_id,
        content=content,
        assertions=assertions,
        required_tests=required_tests,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


def create_agent_run(
    db: Session,
    *,
    mission_id: UUID,
    agent_type: str,
    input: JsonObject,
    feature_task_id: UUID | None = None,
) -> AgentRun:
    agent_run = AgentRun(
        mission_id=mission_id,
        feature_task_id=feature_task_id,
        agent_type=agent_type,
        input=input,
        status=AgentRunStatus.queued,
    )
    db.add(agent_run)
    db.commit()
    db.refresh(agent_run)
    return agent_run


def mark_agent_run_running(db: Session, agent_run: AgentRun) -> AgentRun:
    agent_run.status = AgentRunStatus.running
    agent_run.started_at = datetime.now(UTC)
    db.add(agent_run)
    db.commit()
    db.refresh(agent_run)
    log_mission_event(
        db,
        mission_id=agent_run.mission_id,
        event_type="agent_run_started",
        message=f"Agent run started: {agent_run.agent_type}",
        payload={
            "agent_run_id": str(agent_run.id),
            "agent_type": agent_run.agent_type,
            "feature_task_id": str(agent_run.feature_task_id) if agent_run.feature_task_id else None,
        },
    )
    return agent_run


def complete_agent_run(
    db: Session,
    agent_run: AgentRun,
    *,
    output: JsonObject | None = None,
    error: str | None = None,
) -> AgentRun:
    agent_run.output = output
    agent_run.error = error
    agent_run.status = AgentRunStatus.failed if error else AgentRunStatus.completed
    agent_run.completed_at = datetime.now(UTC)
    db.add(agent_run)
    db.commit()
    db.refresh(agent_run)
    log_mission_event(
        db,
        mission_id=agent_run.mission_id,
        event_type="agent_run_completed",
        message=f"Agent run {agent_run.status.value}: {agent_run.agent_type}",
        payload={
            "agent_run_id": str(agent_run.id),
            "agent_type": agent_run.agent_type,
            "feature_task_id": str(agent_run.feature_task_id) if agent_run.feature_task_id else None,
            "status": agent_run.status.value,
            "error": error,
        },
    )
    return agent_run


def create_validation_report(
    db: Session,
    *,
    mission_id: UUID,
    validator_type: str,
    passed: bool,
    summary: str,
    issues: JsonList,
    milestone_id: UUID | None = None,
    raw_output: JsonObject | None = None,
) -> ValidationReport:
    report = ValidationReport(
        mission_id=mission_id,
        milestone_id=milestone_id,
        validator_type=validator_type,
        passed=passed,
        summary=summary,
        issues=issues,
        raw_output=raw_output,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    log_mission_event(
        db,
        mission_id=mission_id,
        event_type="validation_passed" if passed else "validation_failed",
        message="Validation passed." if passed else "Validation failed.",
        payload={
            "validation_report_id": str(report.id),
            "milestone_id": str(milestone_id) if milestone_id else None,
            "validator_type": validator_type,
            "issues": len(issues),
        },
    )
    return report


def list_mission_decisions(db: Session, mission_id: UUID) -> list[MissionDecision]:
    # Returns every decision ever recorded for the mission, unfiltered. Fine for an MVP mission
    # size; a long-running mission accumulating many decisions would need summarization or
    # capping here before injecting them into prompts.
    statement = (
        select(MissionDecision)
        .where(MissionDecision.mission_id == mission_id)
        .order_by(MissionDecision.created_at.asc())
    )
    return list(db.scalars(statement).all())


def create_mission_decision(
    db: Session,
    *,
    mission_id: UUID,
    key: str,
    value: str,
    source_task_id: UUID | None = None,
) -> MissionDecision:
    decision = MissionDecision(
        mission_id=mission_id,
        source_task_id=source_task_id,
        key=key,
        value=value,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def create_artifact(
    db: Session,
    *,
    mission_id: UUID,
    artifact_type: str,
    path: str,
    agent_run_id: UUID | None = None,
    metadata: JsonObject | None = None,
) -> Artifact:
    artifact = Artifact(
        mission_id=mission_id,
        agent_run_id=agent_run_id,
        artifact_type=artifact_type,
        path=path,
        artifact_metadata=metadata,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@dataclass
class OpenPrResult:
    pr_url: str
    branch: str


def open_mission_pr(
    db: Session,
    *,
    mission_id: UUID,
    github: GitHubService,
) -> OpenPrResult:
    mission = get_mission(db, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"Mission not found: {mission_id}")

    repository = get_repository(db, mission_id)
    if repository is None:
        raise MissionNotReadyError("Mission has no repository. Run /clone first.")
    if not repository.local_path:
        raise MissionNotReadyError("Repository has not been cloned yet. Run /clone first.")
    if not repository.github_owner or not repository.github_repo:
        raise MissionNotReadyError("Repository is not a GitHub repository.")

    mission_branch = f"mission/{str(mission_id)[:8]}"

    try:
        github.push_branch(
            local_path=repository.local_path,
            branch=mission_branch,
            owner=repository.github_owner,
            repo=repository.github_repo,
        )
        pr_url = github.create_pull_request(
            owner=repository.github_owner,
            repo=repository.github_repo,
            head=mission_branch,
            base=repository.default_branch,
            title=f"[Mission] {mission.title}",
            body=mission.goal,
        )
    except GitHubServiceError as exc:
        raise RuntimeError(str(exc)) from exc

    create_artifact(
        db,
        mission_id=mission_id,
        artifact_type="github_pr",
        path=pr_url,
        metadata={"branch": mission_branch, "base": repository.default_branch},
    )
    log_mission_event(
        db,
        mission_id=mission_id,
        event_type="pr_opened",
        message=f"Pull request opened: {pr_url}",
        payload={"pr_url": pr_url, "branch": mission_branch},
    )

    return OpenPrResult(pr_url=pr_url, branch=mission_branch)
