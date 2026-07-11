from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, AgentOutput
from app.api.routes.missions import get_planner_agent, get_spec_agent
from app.core import database as database_module
from app.core.database import Base, get_db
from app.main import app
from app.models import AgentRun, AgentRunStatus, FeatureTask, FeatureTaskType, MissionStatus
from app.workers.tasks import run_agent_task
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class LifecyclePlanner:
    agent_type = "planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created lifecycle test plan.",
            data={
                "milestones": [
                    {
                        "name": "Core behavior",
                        "description": "Create the first backend behavior.",
                        "order_index": 1,
                        "features": [
                            {
                                "title": "Implement core behavior",
                                "description": "Create the core backend behavior.",
                                "task_type": "backend",
                            }
                        ],
                    },
                    {
                        "name": "Documentation",
                        "description": "Document the completed behavior.",
                        "order_index": 2,
                        "features": [
                            {
                                "title": "Document behavior",
                                "description": "Document how the backend behavior works.",
                                "task_type": "docs",
                            }
                        ],
                    },
                ],
                "assumptions": [],
                "risks": [],
            },
        )


class LifecycleSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        command = (
            "python -c \"from pathlib import Path; import sys; "
            "sys.exit(0 if Path('validation_marker.txt').exists() else 1)\""
        )
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created lifecycle validation contract.",
            data={
                "contract_markdown": "# Validation Contract\n\nA marker file proves behavior is complete.",
                "assertions": [
                    {
                        "id": "A1",
                        "description": "validation_marker.txt exists in the repository root.",
                        "validation_method": "integration_test",
                    }
                ],
                "required_tests": [
                    {
                        "name": "marker exists",
                        "type": "shell",
                        "command": command,
                    }
                ],
                "definition_of_done": ["The marker validation command passes."],
            },
        )


@dataclass(frozen=True)
class LifecycleContext:
    client: TestClient
    session_local: sessionmaker
    repo_path: Path
    repo_id: str


@pytest.fixture
def lifecycle_context(tmp_path: Path) -> Iterator[LifecycleContext]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "sample.txt").write_text("hello", encoding="utf-8")

    original_engine = database_module._engine
    original_session_local = database_module._session_local
    database_module._engine = engine
    database_module._session_local = session_local

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_planner_agent] = lambda: LifecyclePlanner()
    app.dependency_overrides[get_spec_agent] = lambda: LifecycleSpec()

    user = persist_test_user(session_local)
    repo = persist_test_repo(session_local, user_id=user.id)
    override_current_user(app, user)

    try:
        yield LifecycleContext(
            client=TestClient(app),
            session_local=session_local,
            repo_path=repo_path,
            repo_id=str(repo.id),
        )
    finally:
        app.dependency_overrides.clear()
        database_module._engine = original_engine
        database_module._session_local = original_session_local
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_mission_lifecycle_failed_validation_fix_then_completion(
    lifecycle_context: LifecycleContext,
) -> None:
    client = lifecycle_context.client

    created = client.post(
        "/missions",
        json={
            "repo_id": lifecycle_context.repo_id,
            "title": "Build lifecycle",
            "goal": "Exercise the orchestrator lifecycle in tests.",
        },
    )
    assert created.status_code == 201
    mission_id = created.json()["id"]

    planned = client.post(f"/missions/{mission_id}/plan")
    assert planned.status_code == 200
    assert len(planned.json()["milestones"]) == 2
    assert len(planned.json()["feature_tasks"]) == 2

    contracted = client.post(f"/missions/{mission_id}/validation-contract")
    assert contracted.status_code == 201
    assert contracted.json()["assertions"][0]["id"] == "A1"
    assert contracted.json()["required_tests"][0]["type"] == "shell"

    repository = client.post(
        f"/missions/{mission_id}/repository",
        json={
            "provider": "local",
            "repo_url": "https://github.com/example/repo",
            "default_branch": "main",
            "local_path": str(lifecycle_context.repo_path),
        },
    )
    assert repository.status_code == 201

    # Approval auto-dispatches the first feature task; capture its AgentRun id
    # instead of driving the mission forward with manual ticks.
    with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
        approved = client.post(f"/missions/{mission_id}/approve-plan")
    assert approved.status_code == 200
    assert approved.json()["status"] == MissionStatus.running.value
    assert approved.json()["milestones"][0]["status"] == "running"
    delay.assert_called_once()
    first_task_run_id = str(delay.call_args.args[0])

    # Running the worker task auto-advances the mission afterward: it runs
    # validators, finds the failure, creates a fix task, and dispatches it -
    # all without any manual tick.
    with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
        first_worker = run_agent_task(first_task_run_id)
    assert first_worker["status"] == "completed"
    delay.assert_called_once()
    fix_task_run_id = str(delay.call_args.args[0])

    failed_body = client.get(f"/missions/{mission_id}").json()
    assert failed_body["status"] == MissionStatus.running.value
    assert failed_body["validation_reports"][0]["passed"] is False

    fix_tasks = [
        task
        for task in failed_body["feature_tasks"]
        if task["task_type"] == FeatureTaskType.fix.value
    ]
    assert len(fix_tasks) == 1
    assert fix_tasks[0]["status"] == "running"
    assert fix_tasks[0]["assigned_agent_type"] == "worker"

    (lifecycle_context.repo_path / "validation_marker.txt").write_text("ok", encoding="utf-8")

    # Completing the fix task auto-advances again: validation passes, the
    # first milestone completes, and the second milestone's task is queued.
    with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
        fix_worker = run_agent_task(fix_task_run_id)
    assert fix_worker["status"] == "completed"
    delay.assert_called_once()
    second_task_run_id = str(delay.call_args.args[0])

    first_pass_body = client.get(f"/missions/{mission_id}").json()
    assert first_pass_body["validation_reports"][0]["passed"] is True
    assert first_pass_body["milestones"][0]["status"] == "completed"
    assert first_pass_body["milestones"][1]["status"] == "running"
    assert first_pass_body["status"] == MissionStatus.running.value

    # Completing the second milestone's task auto-advances the mission all
    # the way to completion - no further ticks needed.
    with patch("app.orchestration.mission_graph.run_agent_task.delay"):
        second_worker = run_agent_task(second_task_run_id)
    assert second_worker["status"] == "completed"

    completed_body = client.get(f"/missions/{mission_id}").json()
    assert completed_body["status"] == MissionStatus.completed.value
    assert all(milestone["status"] == "completed" for milestone in completed_body["milestones"])
    assert completed_body["validation_reports"][0]["passed"] is True

    with lifecycle_context.session_local() as db:
        agent_runs = db.scalars(select(AgentRun)).all()
        feature_tasks = db.scalars(select(FeatureTask)).all()

    assert [run.agent_type for run in agent_runs] == [
        "planner",
        "spec",
        "worker",
        "validator",
        "fix_planner",
        "worker",
        "validator",
        "worker",
        "validator",
    ]
    assert all(run.status == AgentRunStatus.completed for run in agent_runs)
    assert all(task.status.value == "completed" for task in feature_tasks)
