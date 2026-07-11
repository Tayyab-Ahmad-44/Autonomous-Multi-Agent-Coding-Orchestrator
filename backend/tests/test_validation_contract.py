from __future__ import annotations

from unittest import TestCase
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, AgentOutput
from app.api.routes.missions import get_spec_agent
from app.core.database import Base, get_db
from app.main import app
from app.models import AgentRun, AgentRunStatus, FeatureTaskType, ValidationContract
from app.services import missions as mission_service
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class SuccessfulSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created fake validation contract.",
            data={
                "contract_markdown": "# Validation Contract\n\nGET /health returns status ok.",
                "assertions": [
                    {
                        "id": "A1",
                        "description": "GET /health returns JSON with status ok.",
                        "validation_method": "integration_test",
                    }
                ],
                "required_tests": [
                    {
                        "name": "health endpoint",
                        "type": "shell",
                        "command": "curl http://localhost:8000/health",
                    }
                ],
                "definition_of_done": ["All assertions pass."],
            },
        )


class FailingSpec:
    agent_type = "spec"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        raise RuntimeError("spec failed clearly")


class ValidationContractEndpointTests(TestCase):
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

    def test_validation_contract_endpoint_stores_contract_and_agent_run(self) -> None:
        app.dependency_overrides[get_spec_agent] = lambda: SuccessfulSpec()
        mission = self._create_mission_with_plan()

        response = self.client.post(f"/missions/{mission['id']}/validation-contract")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("GET /health", body["content"])
        self.assertEqual(body["assertions"][0]["id"], "A1")
        self.assertEqual(body["required_tests"][0]["type"], "shell")

        with self.session_local() as db:
            contracts = db.scalars(select(ValidationContract)).all()
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(len(contracts), 1)
        self.assertEqual(len(agent_runs), 1)
        self.assertEqual(agent_runs[0].agent_type, "spec")
        self.assertEqual(agent_runs[0].status, AgentRunStatus.completed)

    def test_validation_contract_endpoint_records_failed_agent_run(self) -> None:
        app.dependency_overrides[get_spec_agent] = lambda: FailingSpec()
        mission = self._create_mission_with_plan()

        response = self.client.post(f"/missions/{mission['id']}/validation-contract")

        self.assertEqual(response.status_code, 500)
        with self.session_local() as db:
            agent_run = db.scalars(select(AgentRun)).one()
            contracts = db.scalars(select(ValidationContract)).all()

        self.assertEqual(agent_run.status, AgentRunStatus.failed)
        self.assertIn("spec failed clearly", agent_run.error)
        self.assertEqual(contracts, [])

    def test_validation_contract_endpoint_requires_plan(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        response = self.client.post(f"/missions/{mission['id']}/validation-contract")

        self.assertEqual(response.status_code, 400)

    def _create_mission_with_plan(self) -> dict:
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
        return mission
