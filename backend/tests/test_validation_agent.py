from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Artifact, AgentRun, AgentRunStatus, FeatureTaskType, RepositoryProvider, ValidationReport
from app.services import missions as mission_service
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class ValidationAgentEndpointTests(TestCase):
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

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        self.user = persist_test_user(self.session_local)
        self.repo = persist_test_repo(self.session_local, user_id=self.user.id)
        override_current_user(app, self.user)

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_validate_mission_runs_contract_commands_and_stores_report(self) -> None:
        mission_id = self._create_mission_ready_for_validation(
            required_tests=[
                {
                    "name": "python smoke",
                    "type": "shell",
                    "command": "python -c \"print('ok')\"",
                },
                {
                    "name": "manual review",
                    "type": "manual",
                    "command": "review report",
                },
            ]
        )

        response = self.client.post(f"/missions/{mission_id}/validate")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["passed"])
        self.assertEqual(body["issues"], [])
        self.assertEqual(len(body["raw_output"]["results"]), 1)
        self.assertEqual(body["raw_output"]["results"][0]["exit_code"], 0)
        self.assertEqual(len(body["raw_output"]["skipped"]), 1)

        with self.session_local() as db:
            reports = db.scalars(select(ValidationReport)).all()
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].passed)
        self.assertEqual(len(agent_runs), 1)
        self.assertEqual(agent_runs[0].agent_type, "validator")
        self.assertEqual(agent_runs[0].status, AgentRunStatus.completed)
        self.assertEqual(agent_runs[0].output["data"]["validation_report_id"], str(reports[0].id))

    def test_validate_mission_stores_failed_command_as_issue(self) -> None:
        mission_id = self._create_mission_ready_for_validation(
            required_tests=[
                {
                    "name": "failing smoke",
                    "type": "pytest",
                    "command": (
                        "python -c \"import sys; print('bad'); "
                        "sys.stderr.write('err'); sys.exit(3)\""
                    ),
                }
            ]
        )

        response = self.client.post(f"/missions/{mission_id}/validate")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertFalse(body["passed"])
        self.assertEqual(len(body["issues"]), 1)
        self.assertEqual(body["issues"][0]["exit_code"], 3)
        self.assertIn("bad", body["issues"][0]["stdout"])
        self.assertIn("err", body["issues"][0]["stderr"])

        with self.session_local() as db:
            report = db.scalars(select(ValidationReport)).one()
            agent_run = db.scalars(select(AgentRun)).one()

        self.assertFalse(report.passed)
        self.assertEqual(report.issues[0]["name"], "failing smoke")
        self.assertEqual(agent_run.status, AgentRunStatus.completed)

    def test_validate_mission_runs_playwright_and_stores_media_artifacts(self) -> None:
        script = self.repo_path / "fake_playwright.py"
        script.write_text(
            "\n".join(
                [
                    "from pathlib import Path",
                    "import sys",
                    "Path('test-results/login').mkdir(parents=True, exist_ok=True)",
                    "Path('playwright-report/data').mkdir(parents=True, exist_ok=True)",
                    "Path('test-results/login/screenshot.png').write_bytes(b'png')",
                    "Path('playwright-report/data/video.webm').write_bytes(b'webm')",
                    "print('playwright failed')",
                    "sys.stderr.write('browser error')",
                    "sys.exit(5)",
                ]
            ),
            encoding="utf-8",
        )
        mission_id = self._create_mission_ready_for_validation(
            required_tests=[
                {
                    "name": "Login page loads",
                    "type": "playwright",
                    "command": "python fake_playwright.py",
                }
            ]
        )

        response = self.client.post(f"/missions/{mission_id}/validate")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertFalse(body["passed"])
        self.assertEqual(len(body["issues"]), 1)
        self.assertEqual(body["issues"][0]["type"], "playwright")
        self.assertEqual(body["issues"][0]["exit_code"], 5)
        self.assertIn("playwright failed", body["issues"][0]["stdout"])
        self.assertIn("browser error", body["issues"][0]["stderr"])
        self.assertEqual(len(body["raw_output"]["artifact_ids"]), 2)
        self.assertEqual(len(body["raw_output"]["results"][0]["artifact_ids"]), 2)

        with self.session_local() as db:
            artifacts = db.scalars(select(Artifact).order_by(Artifact.path)).all()
            report = db.scalars(select(ValidationReport)).one()

        self.assertEqual([artifact.artifact_type for artifact in artifacts], ["playwright_artifact", "playwright_artifact"])
        self.assertEqual(
            [artifact.path for artifact in artifacts],
            [
                "playwright-report/data/video.webm",
                "test-results/login/screenshot.png",
            ],
        )
        self.assertEqual(report.issues[0]["artifact_ids"], body["raw_output"]["artifact_ids"])

    def test_validate_mission_semgrep_high_finding_creates_issue(self) -> None:
        semgrep_output = {
            "version": "1.0.0",
            "results": [
                {
                    "check_id": "python.django.security.injection.sql",
                    "path": "app/auth.py",
                    "start": {"line": 12, "col": 4},
                    "extra": {
                        "message": "Possible SQL injection",
                        "severity": "HIGH",
                    },
                },
                {
                    "check_id": "python.lang.best-practice.debug",
                    "path": "app/auth.py",
                    "start": {"line": 20, "col": 1},
                    "extra": {
                        "message": "Debug statement",
                        "severity": "LOW",
                    },
                },
            ],
        }
        script = self.repo_path / "fake_semgrep.py"
        script.write_text(
            f"print({json.dumps(json.dumps(semgrep_output))})\n",
            encoding="utf-8",
        )
        mission_id = self._create_mission_ready_for_validation(
            required_tests=[
                {
                    "name": "Semgrep scan",
                    "type": "semgrep",
                    "command": "python fake_semgrep.py",
                }
            ]
        )

        response = self.client.post(f"/missions/{mission_id}/validate")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertFalse(body["passed"])
        self.assertEqual(len(body["issues"]), 1)
        self.assertEqual(body["issues"][0]["type"], "semgrep")
        self.assertEqual(body["issues"][0]["severity"], "HIGH")
        self.assertEqual(body["issues"][0]["check_id"], "python.django.security.injection.sql")
        self.assertEqual(body["raw_output"]["results"][0]["exit_code"], 0)
        self.assertEqual(
            body["raw_output"]["results"][0]["semgrep"]["parsed"]["results"][0]["extra"]["severity"],
            "HIGH",
        )

        with self.session_local() as db:
            artifact = db.scalars(select(Artifact)).one()
            report = db.scalars(select(ValidationReport)).one()

        self.assertEqual(artifact.artifact_type, "semgrep_output")
        self.assertIn("Possible SQL injection", artifact.artifact_metadata["stdout"])
        self.assertEqual(report.issues[0]["artifact_ids"], [str(artifact.id)])

    def _create_mission_ready_for_validation(self, required_tests: list[dict]) -> str:
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
                description="Create the backend slice.",
                order_index=1,
            )
            mission_service.create_feature_task(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                title="Create login endpoint",
                description="Create a login endpoint.",
                task_type=FeatureTaskType.backend,
            )
            mission_service.upsert_repository(
                db,
                mission_id=mission.id,
                provider=RepositoryProvider.local,
                repo_url="https://github.com/user/repo",
                default_branch="main",
                local_path=str(self.repo_path),
            )
            mission_service.create_validation_contract(
                db,
                mission_id=mission.id,
                content="# Validation Contract",
                assertions=[
                    {
                        "id": "A1",
                        "description": "Required validation commands pass.",
                        "validation_method": "integration_test",
                    }
                ],
                required_tests=required_tests,
            )
            return str(UUID(str(mission.id)))
