from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import database as database_module
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models import Artifact, AgentRun, AgentRunStatus, FeatureTaskStatus, FeatureTaskType, RepositoryProvider
from app.services.codex_service import CodexResult
from app.services import missions as mission_service
from app.workers.tasks import run_agent_task


class CeleryWorkerTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )
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
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        database_module._engine = self.original_engine
        database_module._session_local = self.original_session_local
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_run_agent_task_executes_stub_worker_agent(self) -> None:
        with self.session_local() as db:
            feature_task = self._create_feature_task(db)
            mission_service.upsert_repository(
                db,
                mission_id=feature_task.mission_id,
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )
            agent_run = mission_service.create_agent_run_for_feature_task(db, feature_task)

        result = run_agent_task(str(agent_run.id))

        self.assertEqual(result["status"], "completed")
        with self.session_local() as db:
            stored_run = db.get(AgentRun, agent_run.id)

        self.assertIsNotNone(stored_run)
        self.assertEqual(stored_run.status, AgentRunStatus.completed)
        self.assertIsNotNone(stored_run.started_at)
        self.assertIsNotNone(stored_run.completed_at)
        self.assertEqual(stored_run.output["data"]["feature_task_id"], str(feature_task.id))
        self.assertEqual(
            stored_run.output["data"]["repo_path"].replace("\\", "/"),
            str(self.repo_path).replace("\\", "/"),
        )
        self.assertIn("repo_inspection", stored_run.output["data"])
        self.assertGreaterEqual(len(stored_run.output["data"]["repo_inspection"]), 2)
        with self.session_local() as db:
            artifacts = db.scalars(select(Artifact)).all()

        self.assertGreaterEqual(len(artifacts), 2)
        self.assertTrue(all(artifact.artifact_type == "repo_inspection" for artifact in artifacts))

    def test_run_agent_task_uses_codex_when_enabled(self) -> None:
        with self.session_local() as db:
            feature_task = self._create_feature_task(db)
            mission_service.upsert_repository(
                db,
                mission_id=feature_task.mission_id,
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )
            agent_run = mission_service.create_agent_run_for_feature_task(db, feature_task)

        codex_result = CodexResult(
            command=["codex-test", "exec", "prompt"],
            repo_path=str(self.repo_path),
            stdout="codex changed files",
            stderr="",
            exit_code=0,
            duration_seconds=1.0,
        )
        branch_name = (
            f"mission/{str(feature_task.mission_id).split('-')[0]}"
            f"/task/{str(feature_task.id).split('-')[0]}"
        )
        current_branch = {"name": "main"}

        def fake_git_run(command, cwd, capture_output, text):
            if command[1:] == ["rev-parse", "--is-inside-work-tree"]:
                return subprocess.CompletedProcess(command, 0, stdout="true\n", stderr="")
            if command[1:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return subprocess.CompletedProcess(command, 0, stdout=f"{current_branch['name']}\n", stderr="")
            if command[1:] == ["checkout", branch_name]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="pathspec not found")
            if command[1:] == ["checkout", "-b", branch_name]:
                current_branch["name"] = branch_name
                return subprocess.CompletedProcess(command, 0, stdout="", stderr=f"Switched to {branch_name}")
            if command[1:] == ["diff"]:
                return subprocess.CompletedProcess(command, 0, stdout="diff --git a/sample.txt b/sample.txt\n", stderr="")
            if command[1:] == ["status", "--short"]:
                return subprocess.CompletedProcess(command, 0, stdout=" M sample.txt\n", stderr="")
            if command[1:] == ["add", "-A"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[1:] == ["commit", "-m", "Task: Create login endpoint"]:
                return subprocess.CompletedProcess(command, 0, stdout="[branch abc123] Task", stderr="")
            if command[1:] == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
            raise AssertionError(f"Unexpected git command: {command}")

        with patch.dict(
            os.environ,
            {
                "CODEX_ENABLED": "true",
                "CODEX_COMMAND": "codex-test",
                "CODEX_ALLOW_COMMITS": "false",
                "AUTO_COMMIT": "true",
            },
        ):
            get_settings.cache_clear()
            try:
                with (
                    patch(
                        "app.services.codex_service.CodexService.run_codex_task",
                        return_value=codex_result,
                    ) as run_codex,
                    patch("app.services.git_service.subprocess.run", side_effect=fake_git_run) as git_run,
                ):
                    result = run_agent_task(str(agent_run.id))
            finally:
                get_settings.cache_clear()

        self.assertEqual(result["status"], "completed")
        prompt = run_codex.call_args.kwargs["task_prompt"]
        self.assertEqual(run_codex.call_args.kwargs["repo_path"], str(self.repo_path))
        self.assertIn("Mission goal:", prompt)
        self.assertIn("Build auth", prompt)
        self.assertIn("Create login endpoint", prompt)
        self.assertIn("Worker inspects the repository.", prompt)
        self.assertIn("Modify only files needed for this task.", prompt)
        self.assertIn("Do not commit unless asked.", prompt)
        git_commands = [call.args[0] for call in git_run.call_args_list]
        self.assertIn(["git", "checkout", "-b", branch_name], git_commands)
        self.assertIn(["git", "diff"], git_commands)
        self.assertIn(["git", "commit", "-m", "Task: Create login endpoint"], git_commands)

        with self.session_local() as db:
            stored_run = db.get(AgentRun, agent_run.id)
            stored_task = db.get(type(feature_task), feature_task.id)
            artifacts = db.scalars(select(Artifact)).all()

        self.assertEqual(stored_run.status, AgentRunStatus.completed)
        self.assertEqual(stored_run.output["data"]["codex_result"]["stdout"], "codex changed files")
        self.assertEqual(stored_run.output["data"]["git"]["branch_name"], branch_name)
        self.assertTrue(stored_run.output["data"]["git"]["has_changes"])
        self.assertEqual(stored_run.output["data"]["git"]["latest_commit"], "abc123")
        self.assertEqual(stored_task.status, FeatureTaskStatus.completed)
        self.assertEqual([artifact.artifact_type for artifact in artifacts], ["codex_run", "git_diff"])
        self.assertEqual(artifacts[0].artifact_metadata["result"]["stdout"], "codex changed files")
        self.assertIn("diff --git", artifacts[1].artifact_metadata["diff"])
        self.assertEqual(artifacts[1].artifact_metadata["latest_commit"], "abc123")

    def test_run_agent_task_stores_errors(self) -> None:
        with self.session_local() as db:
            mission = mission_service.create_mission(db, title="Build login", goal="Build auth")
            agent_run = mission_service.create_agent_run(
                db,
                mission_id=mission.id,
                agent_type="missing_agent",
                input={"instructions": "Run missing agent.", "data": {}},
            )

        result = run_agent_task(str(agent_run.id))

        self.assertEqual(result["status"], "failed")
        with self.session_local() as db:
            stored_run = db.get(AgentRun, agent_run.id)

        self.assertEqual(stored_run.status, AgentRunStatus.failed)
        self.assertIn("not registered", stored_run.error)

    def test_run_feature_task_endpoint_creates_agent_run_and_queues_task(self) -> None:
        with self.session_local() as db:
            feature_task = self._create_feature_task(db)
            mission_service.upsert_repository(
                db,
                mission_id=feature_task.mission_id,
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )

        with patch(
            "app.api.routes.feature_tasks.run_agent_task.delay",
            side_effect=lambda agent_run_id: run_agent_task(agent_run_id),
        ):
            response = self.client.post(f"/feature-tasks/{feature_task.id}/run")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], AgentRunStatus.completed.value)

        with self.session_local() as db:
            stored_task = db.get(type(feature_task), feature_task.id)
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(stored_task.status, FeatureTaskStatus.completed)
        self.assertEqual(len(agent_runs), 1)
        self.assertEqual(agent_runs[0].agent_type, "worker")
        self.assertEqual(agent_runs[0].status, AgentRunStatus.completed)

    def test_run_feature_task_endpoint_returns_active_run_without_duplicate_queue(self) -> None:
        with self.session_local() as db:
            feature_task = self._create_feature_task(db)
            mission_service.upsert_repository(
                db,
                mission_id=feature_task.mission_id,
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )

        with patch("app.api.routes.feature_tasks.run_agent_task.delay") as delay:
            first = self.client.post(f"/feature-tasks/{feature_task.id}/run")
            second = self.client.post(f"/feature-tasks/{feature_task.id}/run")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["id"], second.json()["id"])
        delay.assert_called_once()

        with self.session_local() as db:
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(len(agent_runs), 1)
        self.assertEqual(agent_runs[0].status, AgentRunStatus.queued)

    def _create_feature_task(self, db):
        mission = mission_service.create_mission(db, title="Build login", goal="Build auth")
        milestone = mission_service.create_milestone(
            db,
            mission_id=mission.id,
            name="Backend MVP",
            description="Create backend slice.",
            order_index=1,
        )
        mission_service.create_validation_contract(
            db,
            mission_id=mission.id,
            content="# Validation Contract",
            assertions=[
                {
                    "id": "A1",
                    "description": "Worker inspects the repository.",
                    "validation_method": "manual_review",
                }
            ],
            required_tests=[
                {
                    "name": "repo inspection",
                    "type": "manual",
                    "command": "review worker report",
                }
            ],
        )
        return mission_service.create_feature_task(
            db,
            mission_id=mission.id,
            milestone_id=milestone.id,
            title="Create login endpoint",
            description="Implement login endpoint.",
            task_type=FeatureTaskType.backend,
            assigned_agent_type="worker",
        )
