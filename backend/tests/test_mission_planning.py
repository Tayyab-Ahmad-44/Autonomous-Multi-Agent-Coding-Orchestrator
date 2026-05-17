from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, AgentOutput
from app.api.routes.missions import get_planner_agent
from app.core.database import Base, get_db
from app.main import app
from app.models import AgentRun, AgentRunStatus, FeatureTask, Milestone, MissionStatus


class SuccessfulPlanner:
    agent_type = "planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Created fake plan.",
            data={
                "milestones": [
                    {
                        "name": "Backend MVP",
                        "description": "Create the backend slice.",
                        "order_index": 1,
                        "features": [
                            {
                                "title": "Create mission API",
                                "description": "Create endpoints for mission planning.",
                                "task_type": "backend",
                            },
                            {
                                "title": "Test mission API",
                                "description": "Add API-level tests for mission planning.",
                                "task_type": "test",
                            },
                        ],
                    }
                ],
                "assumptions": ["Repository is already scaffolded."],
                "risks": [],
            },
        )


class FailingPlanner:
    agent_type = "planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        raise RuntimeError("planner failed clearly")


class MissionPlanningEndpointTests(TestCase):
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
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_plan_endpoint_creates_milestones_tasks_and_agent_run(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: SuccessfulPlanner()
        mission = self.client.post(
            "/missions",
            json={"title": "Build login system", "goal": "Build email/password auth in this repo"},
        ).json()

        response = self.client.post(f"/missions/{mission['id']}/plan")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], MissionStatus.waiting_for_approval.value)
        self.assertEqual(len(body["milestones"]), 1)
        self.assertEqual(len(body["feature_tasks"]), 2)

        with self.session_local() as db:
            self.assertEqual(len(db.scalars(select(Milestone)).all()), 1)
            self.assertEqual(len(db.scalars(select(FeatureTask)).all()), 2)
            agent_runs = db.scalars(select(AgentRun)).all()

        self.assertEqual(len(agent_runs), 1)
        self.assertEqual(agent_runs[0].status, AgentRunStatus.completed)
        self.assertEqual(agent_runs[0].agent_type, "planner")

    def test_plan_endpoint_records_failed_agent_run(self) -> None:
        app.dependency_overrides[get_planner_agent] = lambda: FailingPlanner()
        mission = self.client.post(
            "/missions",
            json={"title": "Build login system", "goal": "Build email/password auth in this repo"},
        ).json()

        response = self.client.post(f"/missions/{mission['id']}/plan")

        self.assertEqual(response.status_code, 500)
        with self.session_local() as db:
            agent_run = db.scalars(select(AgentRun)).one()

        self.assertEqual(agent_run.status, AgentRunStatus.failed)
        self.assertIn("planner failed clearly", agent_run.error)
