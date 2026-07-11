from __future__ import annotations

from typing import Literal, NotRequired, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents import FixPlannerAgent, PlannerAgent, SpecAgent, ValidatorAgent
from app.core.config import get_settings
from app.models import (
    AgentRun,
    FeatureTask,
    FeatureTaskStatus,
    Mission,
    MissionStatus,
    ValidationContract,
    ValidationReport,
)
from app.services import missions as mission_service
from app.workers.tasks import run_agent_task


GraphMode = Literal["orchestrate", "tick"]


class MissionGraphState(TypedDict):
    mission_id: UUID
    db: Session
    mode: NotRequired[GraphMode]
    planner_agent: NotRequired[PlannerAgent | None]
    spec_agent: NotRequired[SpecAgent | None]
    validator_agent: NotRequired[ValidatorAgent | None]
    fix_planner_agent: NotRequired[FixPlannerAgent | None]
    mission: NotRequired[Mission]
    validation_contract: NotRequired[ValidationContract]
    validation_report: NotRequired[ValidationReport]
    queued_agent_run: NotRequired[AgentRun]
    dispatched_feature_task: NotRequired[FeatureTask]
    has_plan: NotRequired[bool]
    has_validation_contract: NotRequired[bool]
    approval_required: NotRequired[bool]
    validators_passed: NotRequired[bool]
    next_step: NotRequired[str]


async def run_mission_orchestrator(
    db: Session,
    mission_id: UUID,
    *,
    planner_agent: PlannerAgent | None = None,
    spec_agent: SpecAgent | None = None,
) -> MissionGraphState:
    graph = build_mission_graph()
    return await graph.ainvoke(
        {
            "mission_id": mission_id,
            "db": db,
            "mode": "orchestrate",
            "planner_agent": planner_agent,
            "spec_agent": spec_agent,
        }
    )


async def run_mission_tick(
    db: Session,
    mission_id: UUID,
    *,
    planner_agent: PlannerAgent | None = None,
    spec_agent: SpecAgent | None = None,
    validator_agent: ValidatorAgent | None = None,
    fix_planner_agent: FixPlannerAgent | None = None,
) -> MissionGraphState:
    graph = build_mission_graph()
    return await graph.ainvoke(
        {
            "mission_id": mission_id,
            "db": db,
            "mode": "tick",
            "planner_agent": planner_agent,
            "spec_agent": spec_agent,
            "validator_agent": validator_agent,
            "fix_planner_agent": fix_planner_agent,
        }
    )


_PAUSE_STEPS = {
    "wait_for_approval",
    "waiting_for_active_agent_run",
    "worker_queued",
    "worker_retry_queued",
    "task_already_queued",
    "no_pending_feature_task",
    "agent_retry_limit_exceeded",
    "validation_loop_limit_exceeded",
    "complete_mission",
    "stop",
}


async def run_mission_until_blocked(
    db: Session,
    mission_id: UUID,
    *,
    validator_agent: ValidatorAgent | None = None,
    fix_planner_agent: FixPlannerAgent | None = None,
    max_iterations: int = 50,
) -> MissionGraphState:
    """Repeatedly tick the mission graph until it hits a state that requires
    waiting on something external (an in-flight Celery job, human approval, or
    mission completion/failure). This is what makes mission execution
    autonomous after approval instead of requiring a manual "tick" per step.
    """
    state: MissionGraphState | None = None
    for _ in range(max_iterations):
        state = await run_mission_tick(
            db,
            mission_id,
            validator_agent=validator_agent,
            fix_planner_agent=fix_planner_agent,
        )
        if state.get("next_step") in _PAUSE_STEPS:
            break
    if state is None:
        raise mission_service.MissionNotFoundError(f"Mission not found: {mission_id}")
    return state


def build_mission_graph():
    graph = StateGraph(MissionGraphState)

    graph.add_node("load_mission", load_mission)
    graph.add_node("plan_mission", plan_mission)
    graph.add_node("generate_validation_contract", generate_validation_contract)
    graph.add_node("wait_for_approval", wait_for_approval)
    graph.add_node("dispatch_next_tasks", dispatch_next_tasks)
    graph.add_node("run_validators", run_validators)
    graph.add_node("decide_next_step", decide_next_step)
    graph.add_node("complete_mission", complete_mission)

    graph.add_edge(START, "load_mission")
    graph.add_conditional_edges(
        "load_mission",
        route_after_load,
        {
            "plan": "plan_mission",
            "contract": "generate_validation_contract",
            "wait": "wait_for_approval",
            "dispatch": "dispatch_next_tasks",
            "validate": "run_validators",
            "complete": "complete_mission",
            "stop": END,
        },
    )
    graph.add_conditional_edges(
        "plan_mission",
        route_after_plan,
        {
            "contract": "generate_validation_contract",
            "stop": END,
        },
    )
    graph.add_conditional_edges(
        "generate_validation_contract",
        route_after_validation_contract,
        {
            "wait": "wait_for_approval",
            "stop": END,
        },
    )
    graph.add_edge("wait_for_approval", END)
    graph.add_edge("dispatch_next_tasks", END)
    graph.add_edge("run_validators", "decide_next_step")
    graph.add_conditional_edges(
        "decide_next_step",
        route_after_decision,
        {
            "complete": "complete_mission",
            "stop": END,
        },
    )
    graph.add_edge("complete_mission", END)

    return graph.compile()


async def load_mission(state: MissionGraphState) -> MissionGraphState:
    mission = mission_service.get_mission_with_details(state["db"], state["mission_id"])
    if mission is None:
        raise mission_service.MissionNotFoundError(f"Mission not found: {state['mission_id']}")
    if state.get("mode") == "tick" and mission.status in {MissionStatus.running, MissionStatus.validating}:
        mission = mission_service.reconcile_current_milestone_task_statuses(
            state["db"],
            state["mission_id"],
        )

    return {
        **state,
        "mission": mission,
        "has_plan": len(mission.feature_tasks) > 0,
        "has_validation_contract": len(mission.validation_contracts) > 0,
        "next_step": route_after_load_for_mission(mission),
    }


async def plan_mission(state: MissionGraphState) -> MissionGraphState:
    mission = await mission_service.run_planning_for_mission(
        state["db"],
        state["mission_id"],
        planner_agent=state.get("planner_agent"),
    )
    return {
        **state,
        "mission": mission,
        "has_plan": True,
        "next_step": "generate_validation_contract",
    }


async def generate_validation_contract(state: MissionGraphState) -> MissionGraphState:
    contract = await mission_service.generate_validation_contract(
        state["db"],
        state["mission_id"],
        spec_agent=state.get("spec_agent"),
    )
    mission = _get_required_mission(state)
    return {
        **state,
        "mission": mission,
        "validation_contract": contract,
        "has_validation_contract": True,
        "next_step": "wait_for_approval",
    }


async def wait_for_approval(state: MissionGraphState) -> MissionGraphState:
    mission = mission_service.get_mission(state["db"], state["mission_id"])
    if mission is None:
        raise mission_service.MissionNotFoundError(f"Mission not found: {state['mission_id']}")

    mission_service.set_mission_status(state["db"], mission, MissionStatus.waiting_for_approval)
    return {
        **state,
        "mission": _get_required_mission(state),
        "approval_required": True,
        "next_step": "wait_for_approval",
    }


async def dispatch_next_tasks(state: MissionGraphState) -> MissionGraphState:
    mission = _mission_from_state(state)
    if mission_service.mission_has_active_agent_runs(mission):
        return {
            **state,
            "mission": _get_required_mission(state),
            "next_step": "waiting_for_active_agent_run",
        }

    failed_task = mission_service.get_failed_feature_task_in_current_milestone(mission)
    if failed_task is not None:
        return _dispatch_failed_task_retry_or_fail(state, mission, failed_task)

    feature_task = mission_service.get_next_pending_feature_task_in_current_milestone(mission)
    if feature_task is None:
        return {
            **state,
            "mission": _get_required_mission(state),
            "next_step": "no_pending_feature_task",
        }
    if mission_service.feature_task_has_active_agent_run(mission, feature_task.id):
        return {
            **state,
            "mission": _get_required_mission(state),
            "next_step": "task_already_queued",
        }

    agent_run = mission_service.create_worker_agent_run_for_feature_task(state["db"], feature_task)
    mission_service.set_feature_task_status(state["db"], feature_task, FeatureTaskStatus.running)
    run_agent_task.delay(str(agent_run.id))

    return {
        **state,
        "mission": _get_required_mission(state),
        "queued_agent_run": agent_run,
        "dispatched_feature_task": feature_task,
        "next_step": "worker_queued",
    }


async def run_validators(state: MissionGraphState) -> MissionGraphState:
    mission_service.mark_current_milestone_validating(state["db"], state["mission_id"])
    report = await mission_service.run_validation_for_mission(
        state["db"],
        state["mission_id"],
        validator_agent=state.get("validator_agent"),
    )
    return {
        **state,
        "mission": _get_required_mission(state),
        "validation_report": report,
        "validators_passed": report.passed,
        "next_step": "decide_next_step",
    }


async def decide_next_step(state: MissionGraphState) -> MissionGraphState:
    report = state.get("validation_report")
    if report is None:
        raise ValueError("Validation decision requires a ValidationReport.")

    if report.passed:
        mission = mission_service.advance_after_passed_validation(state["db"], state["mission_id"])
        next_step = "complete_mission" if mission.status == MissionStatus.completed else "milestone_advanced"
        return {
            **state,
            "mission": mission,
            "next_step": next_step,
        }

    settings = get_settings()
    failed_loop_count = mission_service.count_failed_validation_reports_for_milestone(
        state["db"],
        mission_id=report.mission_id,
        milestone_id=report.milestone_id,
    )
    if failed_loop_count > settings.max_validation_loops:
        mission = _get_required_mission(state)
        failed = mission_service.fail_mission_for_intervention(
            state["db"],
            mission,
            message="Validation loop limit exceeded; human intervention required.",
            payload={
                "validation_report_id": str(report.id),
                "milestone_id": str(report.milestone_id) if report.milestone_id else None,
                "failed_validation_loops": failed_loop_count,
                "max_validation_loops": settings.max_validation_loops,
            },
        )
        return {
            **state,
            "mission": failed,
            "next_step": "validation_loop_limit_exceeded",
        }

    mission = await mission_service.create_fix_tasks_from_validation_report(
        state["db"],
        report.id,
        fix_planner_agent=state.get("fix_planner_agent"),
    )
    return {
        **state,
        "mission": mission,
        "next_step": "fix_tasks_created",
    }


async def complete_mission(state: MissionGraphState) -> MissionGraphState:
    mission = mission_service.get_mission(state["db"], state["mission_id"])
    if mission is None:
        raise mission_service.MissionNotFoundError(f"Mission not found: {state['mission_id']}")

    mission_service.set_mission_status(state["db"], mission, MissionStatus.completed)
    return {**state, "mission": _get_required_mission(state), "next_step": "complete_mission"}


def route_after_load(state: MissionGraphState) -> Literal[
    "plan",
    "contract",
    "wait",
    "dispatch",
    "validate",
    "complete",
    "stop",
]:
    mission = _mission_from_state(state)
    next_step = route_after_load_for_mission(mission)
    if next_step == "plan_mission":
        return "plan"
    if next_step == "generate_validation_contract":
        return "contract"
    if next_step == "wait_for_approval":
        return "wait"
    if next_step == "dispatch_next_tasks":
        return "dispatch"
    if next_step == "run_validators":
        return "validate"
    if next_step == "complete_mission":
        return "complete"
    return "stop"


def route_after_load_for_mission(mission: Mission) -> str:
    if not mission.feature_tasks:
        return "plan_mission"
    if not mission.validation_contracts:
        return "generate_validation_contract"
    if mission.status in {MissionStatus.completed, MissionStatus.failed}:
        return "stop"
    if mission.status not in {MissionStatus.running, MissionStatus.validating}:
        return "wait_for_approval"
    if mission_service.mission_has_active_agent_runs(mission):
        return "wait_for_agents"
    if mission_service.get_failed_feature_task_in_current_milestone(mission) is not None:
        return "dispatch_next_tasks"
    if mission_service.get_next_pending_feature_task_in_current_milestone(mission) is not None:
        return "dispatch_next_tasks"
    if mission_service.current_milestone_has_running_tasks(mission):
        return "wait_for_workers"
    if mission_service.current_milestone_tasks_are_completed(mission):
        return "run_validators"
    return "stop"


def route_after_plan(state: MissionGraphState) -> Literal["contract", "stop"]:
    return "contract" if state.get("mode") == "orchestrate" else "stop"


def route_after_validation_contract(state: MissionGraphState) -> Literal["wait", "stop"]:
    return "wait" if state.get("mode") == "orchestrate" else "stop"


def route_after_decision(state: MissionGraphState) -> Literal["complete", "stop"]:
    return "stop"


def _dispatch_failed_task_retry_or_fail(
    state: MissionGraphState,
    mission: Mission,
    feature_task: FeatureTask,
) -> MissionGraphState:
    settings = get_settings()
    failed_attempts = mission_service.count_failed_agent_runs_for_feature_task(mission, feature_task.id)
    if failed_attempts > settings.max_agent_retries:
        failed = mission_service.fail_mission_for_intervention(
            state["db"],
            mission,
            message="Agent retry limit exceeded; human intervention required.",
            payload={
                "feature_task_id": str(feature_task.id),
                "failed_attempts": failed_attempts,
                "max_agent_retries": settings.max_agent_retries,
            },
        )
        return {
            **state,
            "mission": failed,
            "next_step": "agent_retry_limit_exceeded",
        }

    agent_run = mission_service.create_worker_agent_run_for_feature_task(state["db"], feature_task)
    mission_service.set_feature_task_status(state["db"], feature_task, FeatureTaskStatus.running)
    run_agent_task.delay(str(agent_run.id))

    return {
        **state,
        "mission": _get_required_mission(state),
        "queued_agent_run": agent_run,
        "dispatched_feature_task": feature_task,
        "next_step": "worker_retry_queued",
    }


def _mission_from_state(state: MissionGraphState) -> Mission:
    mission = state.get("mission")
    if mission is None:
        raise mission_service.MissionNotFoundError(f"Mission not loaded: {state['mission_id']}")
    return mission


def _get_required_mission(state: MissionGraphState) -> Mission:
    mission = mission_service.get_mission_with_details(state["db"], state["mission_id"])
    if mission is None:
        raise mission_service.MissionNotFoundError(f"Mission not found: {state['mission_id']}")
    return mission
