from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, AgentOutput
from app.api.routes.missions import get_planner_agent, get_spec_agent, stream_mission_events
from app.core import database as database_module
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    AgentRun,
    AgentRunStatus,
    FeatureTask,
    FeatureTaskStatus,
    FeatureTaskType,
    Milestone,
    MilestoneStatus,
    MissionEvent,
    MissionStatus,
    RepositoryProvider,
    ValidationReport,
)
from app.orchestration.mission_graph import build_mission_graph
from app.services import missions as mission_service
from app.workers.tasks import run_agent_task
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class OrchestratorPlanner:
    agent_type = "planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created orchestrator fake plan.",
            data={
                "milestones": [
                    {
                        "name": "Backend MVP",
                        "description": "Create the backend slice.",
                        "order_index": 1,
                        "features": [
                            {
                                "title": "Create mission API",
                                "description": "Create endpoints for mission orchestration.",
                                "task_type": "backend",
                            },
                            {
                                "title": "Test mission API",
                                "description": "Add tests for mission orchestration.",
                                "task_type": "test",
                            },
                        ],
                    }
                ],
                "assumptions": [],
                "risks": [],
            },
        )


class OrchestratorSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created orchestrator fake validation contract.",
            data={
                "contract_markdown": "# Validation Contract\n\nMission API behavior is observable.",
                "assertions": [
                    {
                        "id": "A1",
                        "description": "Mission orchestration creates a plan and validation contract.",
                        "validation_method": "integration_test",
                    }
                ],
                "required_tests": [
                    {
                        "name": "mission orchestration endpoint",
                        "type": "pytest",
                        "command": "pytest tests/test_mission_orchestrator.py",
                    }
                ],
                "definition_of_done": ["The mission waits for approval before workers start."],
            },
        )


class SingleTaskPlanner:
    agent_type = "planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created single task plan.",
            data={
                "milestones": [
                    {
                        "name": "Backend MVP",
                        "description": "Create the backend slice.",
                        "order_index": 1,
                        "features": [
                            {
                                "title": "Create mission API",
                                "description": "Create endpoints for mission orchestration.",
                                "task_type": "backend",
                            }
                        ],
                    }
                ],
                "assumptions": [],
                "risks": [],
            },
        )


class PassingTickSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created passing validation contract.",
            data={
                "contract_markdown": "# Validation Contract\n\nPython smoke command passes.",
                "assertions": [
                    {
                        "id": "A1",
                        "description": "The smoke command exits successfully.",
                        "validation_method": "integration_test",
                    }
                ],
                "required_tests": [
                    {
                        "name": "python smoke",
                        "type": "shell",
                        "command": "python -c \"print('ok')\"",
                    }
                ],
                "definition_of_done": ["Smoke command passes."],
            },
        )


class FailingTickSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created failing validation contract.",
            data={
                "contract_markdown": "# Validation Contract\n\nPython smoke command fails.",
                "assertions": [
                    {
                        "id": "A1",
                        "description": "The smoke command exposes a validation issue.",
                        "validation_method": "integration_test",
                    }
                ],
                "required_tests": [
                    {
                        "name": "failing smoke",
                        "type": "shell",
                        "command": (
                            "python -c \"import sys; print('bad'); "
                            "sys.stderr.write('err'); sys.exit(2)\""
                        ),
                    }
                ],
                "definition_of_done": ["Smoke command passes after fixes."],
            },
        )


class MissionOrchestratorEndpointTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        (self.repo_path / "sample.txt").write_text("hello", encoding="utf-8")
        self.original_engine = database_module._engine
        self.original_session_local = database_module._session_local
        database_module._engine = self.engine
        database_module._session_local = self.session_local

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_planner_agent] = lambda: OrchestratorPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: OrchestratorSpec()

        self.user = persist_test_user(self.session_local)
        self.repo = persist_test_repo(self.session_local, user_id=self.user.id)
        override_current_user(app, self.user)

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        database_module._engine = self.original_engine
        database_module._session_local = self.original_session_local
        get_settings.cache_clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_graph_compiles(self) -> None:
        self.assertIsNotNone(build_mission_graph())

    def test_create_mission_records_event_and_detail_returns_timeline(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        response = self.client.get(f"/missions/{mission['id']}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["event_type"], "mission_created")
        self.assertEqual(body["events"][0]["payload"], {"title": "Build login system"})

        with self.session_local() as db:
            events = db.scalars(select(MissionEvent)).all()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "Mission created: Build login system")

    def test_orchestrate_endpoint_creates_plan_contract_and_waits_for_approval(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        response = self.client.post(f"/missions/{mission['id']}/orchestrate")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.waiting_for_approval.value)
        self.assertEqual(len(body["milestones"]), 1)
        self.assertEqual(len(body["feature_tasks"]), 2)
        self.assertIsNotNone(body["validation_contract"])
        self.assertEqual(body["validation_contract"]["assertions"][0]["id"], "A1")

        with self.session_local() as db:
            self.assertEqual(len(db.scalars(select(Milestone)).all()), 1)
            self.assertEqual(len(db.scalars(select(FeatureTask)).all()), 2)
            agent_runs = db.scalars(select(AgentRun)).all()
            events = db.scalars(select(MissionEvent)).all()

        self.assertEqual([run.agent_type for run in agent_runs], ["planner", "spec"])
        self.assertTrue(all(run.status == AgentRunStatus.completed for run in agent_runs))
        event_types = {event.event_type for event in events}
        self.assertIn("mission_created", event_types)
        self.assertIn("agent_run_started", event_types)
        self.assertIn("agent_run_completed", event_types)
        self.assertIn("plan_generated", event_types)
        self.assertIn("validation_contract_generated", event_types)
        self.assertTrue(
            any(
                event.event_type == "plan_generated"
                and event.payload is not None
                and event.payload["milestones"] == 1
                for event in events
            )
        )
        self.assertIn("plan_generated", {event["event_type"] for event in body["events"]})

    def test_mission_event_stream_emits_current_mission_snapshot(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        with self.session_local() as db:
            event = asyncio.run(
                stream_mission_events(db, UUID(mission["id"]), interval_seconds=0).__anext__()
            )

        self.assertIn("event: mission", event)
        self.assertIn('"status":"draft"', event)
        self.assertIn('"feature_tasks":[]', event)
        self.assertIn('"validation_reports":[]', event)

    def test_tick_moves_mission_through_first_worker_and_passing_validation(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: PassingTickSpec()
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        planned = self.client.post(f"/missions/{mission['id']}/tick")
        self.assertEqual(planned.status_code, 200)
        self.assertEqual(len(planned.json()["feature_tasks"]), 1)
        self.assertIsNone(planned.json()["validation_contract"])

        contracted = self.client.post(f"/missions/{mission['id']}/tick")
        self.assertEqual(contracted.status_code, 200)
        self.assertIsNotNone(contracted.json()["validation_contract"])

        waiting = self.client.post(f"/missions/{mission['id']}/tick")
        self.assertEqual(waiting.status_code, 200)
        self.assertEqual(waiting.json()["status"], MissionStatus.waiting_for_approval.value)

        self._set_repository(mission["id"])
        approved = self.client.post(f"/missions/{mission['id']}/approve-plan")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], MissionStatus.running.value)

        with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
            dispatched = self.client.post(f"/missions/{mission['id']}/tick")

        self.assertEqual(dispatched.status_code, 200)
        self.assertEqual(dispatched.json()["feature_tasks"][0]["status"], FeatureTaskStatus.running.value)
        delay.assert_called_once()

        with self.session_local() as db:
            feature_task = db.scalars(select(FeatureTask)).one()
            worker_run = db.scalars(select(AgentRun).where(AgentRun.agent_type == "worker")).one()
            mission_service.mark_agent_run_running(db, worker_run)
            mission_service.complete_agent_run(
                db,
                worker_run,
                output={"status": "completed", "summary": "Worker completed.", "data": {}},
            )
            mission_service.set_feature_task_status(db, feature_task, FeatureTaskStatus.completed)

        completed = self.client.post(f"/missions/{mission['id']}/tick")
        self.assertEqual(completed.status_code, 200)
        body = completed.json()
        self.assertEqual(body["status"], MissionStatus.completed.value)
        self.assertEqual(body["milestones"][0]["status"], MilestoneStatus.completed.value)
        self.assertTrue(body["validation_reports"][0]["passed"])

        with self.session_local() as db:
            agent_runs = db.scalars(select(AgentRun)).all()
            events = db.scalars(select(MissionEvent)).all()

        self.assertEqual([run.agent_type for run in agent_runs], ["planner", "spec", "worker", "validator"])
        event_types = {event.event_type for event in events}
        self.assertIn("task_queued", event_types)
        self.assertIn("validation_passed", event_types)
        self.assertIn("milestone_completed", event_types)
        self.assertIn("mission_completed", event_types)
        self.assertEqual(
            len([event for event in events if event.event_type == "mission_completed"]),
            1,
        )

    def test_tick_does_not_duplicate_worker_run_for_queued_task(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: PassingTickSpec()
        mission = self._create_planned_approved_single_task_mission()

        with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
            first_tick = self.client.post(f"/missions/{mission['id']}/tick")
            second_tick = self.client.post(f"/missions/{mission['id']}/tick")

        self.assertEqual(first_tick.status_code, 200)
        self.assertEqual(second_tick.status_code, 200)
        delay.assert_called_once()
        with self.session_local() as db:
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(len(agent_runs), 3)
        self.assertEqual([run.agent_type for run in agent_runs], ["planner", "spec", "worker"])
        self.assertEqual(agent_runs[-1].status, AgentRunStatus.queued)

    def test_tick_retries_failed_task_then_fails_when_retry_limit_is_exceeded(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: PassingTickSpec()
        mission = self._create_planned_approved_single_task_mission()
        with self.session_local() as db:
            task = db.scalars(select(FeatureTask)).one()
            first_run = mission_service.create_worker_agent_run_for_feature_task(db, task)
            mission_service.mark_agent_run_running(db, first_run)
            mission_service.complete_agent_run(db, first_run, error="worker failed")
            mission_service.set_feature_task_status(db, task, FeatureTaskStatus.failed)

        with patch.dict(os.environ, {"MAX_AGENT_RETRIES": "1"}):
            get_settings.cache_clear()
            try:
                with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
                    retry_tick = self.client.post(f"/missions/{mission['id']}/tick")
                self.assertEqual(retry_tick.status_code, 200)
                self.assertEqual(retry_tick.json()["status"], MissionStatus.running.value)
                delay.assert_called_once()

                with self.session_local() as db:
                    retry_run = db.scalars(
                        select(AgentRun)
                        .where(AgentRun.agent_type == "worker")
                        .where(AgentRun.status == AgentRunStatus.queued)
                        .order_by(AgentRun.created_at.desc())
                    ).first()
                    task = db.scalars(select(FeatureTask)).one()
                    mission_service.mark_agent_run_running(db, retry_run)
                    mission_service.complete_agent_run(db, retry_run, error="worker failed again")
                    mission_service.set_feature_task_status(db, task, FeatureTaskStatus.failed)

                failed_tick = self.client.post(f"/missions/{mission['id']}/tick")
            finally:
                get_settings.cache_clear()

        self.assertEqual(failed_tick.status_code, 200)
        body = failed_tick.json()
        self.assertEqual(body["status"], MissionStatus.failed.value)
        self.assertEqual(body["milestones"][0]["status"], MilestoneStatus.failed.value)
        with self.session_local() as db:
            worker_runs = db.scalars(select(AgentRun).where(AgentRun.agent_type == "worker")).all()

        self.assertEqual(len(worker_runs), 2)

    def test_tick_fails_mission_when_validation_loop_limit_is_exceeded(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: FailingTickSpec()
        mission = self._create_planned_approved_single_task_mission()
        with self.session_local() as db:
            task = db.scalars(select(FeatureTask)).one()
            mission_service.set_feature_task_status(db, task, FeatureTaskStatus.completed)

        with patch.dict(os.environ, {"MAX_VALIDATION_LOOPS": "0"}):
            get_settings.cache_clear()
            try:
                response = self.client.post(f"/missions/{mission['id']}/tick")
            finally:
                get_settings.cache_clear()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.failed.value)
        self.assertEqual(body["milestones"][0]["status"], MilestoneStatus.failed.value)
        self.assertFalse(body["validation_reports"][0]["passed"])
        self.assertEqual(
            [task for task in body["feature_tasks"] if task["task_type"] == FeatureTaskType.fix.value],
            [],
        )

    def test_tick_can_complete_end_to_end_with_stub_worker(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: PassingTickSpec()
        mission = self._create_planned_approved_single_task_mission()

        with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
            worker_tick = self.client.post(f"/missions/{mission['id']}/tick")
        run_agent_task(delay.call_args.args[0])
        completed_tick = self.client.post(f"/missions/{mission['id']}/tick")

        self.assertEqual(worker_tick.status_code, 200)
        self.assertEqual(completed_tick.status_code, 200)
        self.assertEqual(completed_tick.json()["status"], MissionStatus.completed.value)
        with self.session_local() as db:
            worker_run = db.scalars(select(AgentRun).where(AgentRun.agent_type == "worker")).one()
            task = db.scalars(select(FeatureTask)).one()

        self.assertEqual(worker_run.status, AgentRunStatus.completed)
        self.assertEqual(task.status, FeatureTaskStatus.completed)

    def test_tick_creates_fix_tasks_after_failed_validation(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SingleTaskPlanner()
        app.dependency_overrides[get_spec_agent] = lambda: FailingTickSpec()
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        self.client.post(f"/missions/{mission['id']}/tick")
        self.client.post(f"/missions/{mission['id']}/tick")
        self._set_repository(mission["id"])
        self.client.post(f"/missions/{mission['id']}/approve-plan")

        with self.session_local() as db:
            feature_task = db.scalars(select(FeatureTask)).one()
            mission_service.set_feature_task_status(db, feature_task, FeatureTaskStatus.completed)

        response = self.client.post(f"/missions/{mission['id']}/tick")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.running.value)
        self.assertFalse(body["validation_reports"][0]["passed"])

        fix_tasks = [
            task for task in body["feature_tasks"] if task["task_type"] == FeatureTaskType.fix.value
        ]
        self.assertEqual(len(fix_tasks), 1)
        self.assertEqual(fix_tasks[0]["status"], FeatureTaskStatus.pending.value)
        self.assertEqual(fix_tasks[0]["assigned_agent_type"], "worker")

        with self.session_local() as db:
            report = db.scalars(select(ValidationReport)).one()
            agent_runs = db.scalars(select(AgentRun)).all()
            events = db.scalars(select(MissionEvent)).all()

        self.assertFalse(report.passed)
        self.assertEqual(
            [run.agent_type for run in agent_runs],
            ["planner", "spec", "validator", "fix_planner"],
        )
        event_types = {event.event_type for event in events}
        self.assertIn("validation_failed", event_types)
        self.assertIn("fix_tasks_created", event_types)

    def test_create_fix_tasks_from_validation_report_service_creates_tasks_and_agent_run(self) -> None:
        with self.session_local() as db:
            mission = mission_service.create_mission(
                db,
                owner_id=self.user.id,
                repo_id=self.repo.id,
                title="Build login system",
                goal="Build email/password auth in this repo",
            )
            milestone = mission_service.create_milestone(
                db,
                mission_id=mission.id,
                name="Backend MVP",
                description="Create auth endpoints.",
                order_index=1,
            )
            mission_service.create_validation_contract(
                db,
                mission_id=mission.id,
                content="# Validation Contract",
                assertions=[
                    {
                        "id": "A1",
                        "description": "Login command succeeds.",
                        "validation_method": "integration_test",
                    }
                ],
                required_tests=[
                    {
                        "name": "login smoke",
                        "type": "shell",
                        "command": "python -c \"print('ok')\"",
                    }
                ],
            )
            report = mission_service.create_validation_report(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                validator_type="validator",
                passed=False,
                summary="Validation failed: 2 executable test(s) run.",
                issues=[
                    {
                        "name": "login smoke",
                        "type": "shell",
                        "command": "python -m pytest tests/test_auth.py",
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "assert login failed",
                    },
                    {
                        "name": "password reset smoke",
                        "type": "shell",
                        "command": "python -m pytest tests/test_password_reset.py",
                        "exit_code": 1,
                        "stdout": "bad reset",
                        "stderr": "",
                    },
                ],
                raw_output={},
            )
            report_id = report.id

        with self.session_local() as db:
            asyncio.run(mission_service.create_fix_tasks_from_validation_report(db, report_id))
            fix_tasks = db.scalars(
                select(FeatureTask).where(FeatureTask.task_type == FeatureTaskType.fix)
            ).all()
            agent_run = db.scalars(select(AgentRun)).one()

        self.assertEqual(len(fix_tasks), 2)
        self.assertTrue(all(task.assigned_agent_type == "worker" for task in fix_tasks))
        self.assertTrue(all(task.status == FeatureTaskStatus.pending for task in fix_tasks))
        self.assertIn("login smoke", fix_tasks[0].title)
        self.assertEqual(agent_run.agent_type, "fix_planner")
        self.assertEqual(agent_run.status, AgentRunStatus.completed)
        self.assertEqual(agent_run.input["data"]["mission_goal"], "Build email/password auth in this repo")
        self.assertIn("validation_contract", agent_run.input["data"])
        self.assertIn("failed_milestone", agent_run.input["data"])

    def _set_repository(self, mission_id: str) -> None:
        with self.session_local() as db:
            mission_service.upsert_repository(
                db,
                mission_id=UUID(mission_id),
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )

    def _create_planned_approved_single_task_mission(self) -> dict:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()
        self.client.post(f"/missions/{mission['id']}/tick")
        self.client.post(f"/missions/{mission['id']}/tick")
        self._set_repository(mission["id"])
        self.client.post(f"/missions/{mission['id']}/approve-plan")
        return mission
