from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    MissionStatus,
    ValidationContract,
)
from app.services import missions as mission_service
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class ApprovalFlowEndpointTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

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

    def test_mission_cannot_be_approved_without_validation_contract(self) -> None:
        mission = self._create_planned_mission(include_contract=False)

        response = self.client.post(f"/missions/{mission['id']}/approve-plan")

        self.assertEqual(response.status_code, 400)
        self.assertIn("validation contract", response.json()["detail"])

    def test_approval_changes_mission_status_to_running_and_starts_the_first_task(self) -> None:
        mission = self._create_planned_mission(include_contract=True)

        with patch("app.orchestration.mission_graph.run_agent_task.delay") as delay:
            response = self.client.post(f"/missions/{mission['id']}/approve-plan")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.running.value)
        self.assertEqual(body["current_milestone_id"], body["milestones"][0]["id"])
        self.assertEqual(body["milestones"][0]["status"], MilestoneStatus.running.value)
        # Approval now kicks off the mission autonomously: the first feature
        # task is dispatched to a worker agent immediately, not left pending.
        self.assertEqual(body["feature_tasks"][0]["status"], FeatureTaskStatus.running.value)
        delay.assert_called_once()

    def test_reject_plan_records_feedback_and_resets_when_requested(self) -> None:
        mission = self._create_planned_mission(include_contract=True)

        response = self.client.post(
            f"/missions/{mission['id']}/reject-plan",
            params={"reset": True},
            json={"feedback": "Too broad for an MVP."},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.draft.value)
        self.assertEqual(body["milestones"], [])
        self.assertEqual(body["feature_tasks"], [])
        self.assertIsNone(body["validation_contract"])

        with self.session_local() as db:
            agent_run = db.scalars(select(AgentRun)).one()
            self.assertEqual(db.scalars(select(Milestone)).all(), [])
            self.assertEqual(db.scalars(select(FeatureTask)).all(), [])
            self.assertEqual(db.scalars(select(ValidationContract)).all(), [])

        self.assertEqual(agent_run.agent_type, "human_feedback")
        self.assertEqual(agent_run.status, AgentRunStatus.completed)
        self.assertEqual(agent_run.output["feedback"], "Too broad for an MVP.")

    def _create_planned_mission(self, *, include_contract: bool) -> dict:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()
        mission_id = UUID(mission["id"])
        with self.session_local() as db:
            milestone = mission_service.create_milestone(
                db,
                mission_id=mission_id,
                name="Backend MVP",
                description="Create the backend slice.",
                order_index=1,
            )
            mission_service.create_feature_task(
                db,
                mission_id=mission_id,
                milestone_id=milestone.id,
                title="Create mission API",
                description="Create endpoints for mission planning.",
                task_type=FeatureTaskType.backend,
            )
            if include_contract:
                mission_service.create_validation_contract(
                    db,
                    mission_id=mission_id,
                    content="# Validation Contract",
                    assertions=[
                        {
                            "id": "A1",
                            "description": "GET /health returns status ok.",
                            "validation_method": "integration_test",
                        }
                    ],
                    required_tests=[
                        {
                            "name": "health endpoint",
                            "type": "shell",
                            "command": "curl http://localhost:8000/health",
                        }
                    ],
                )
        return mission
