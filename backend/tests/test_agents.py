import asyncio
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from app.agents import (
    AgentContext,
    AgentInput,
    FixPlannerAgent,
    PlannerAgent,
    ResearchAgent,
    SpecAgent,
    ValidatorAgent,
    WorkerAgent,
    build_default_registry,
)


class FakePlannerLLM:
    async def generate_json(self, system_prompt, user_prompt, schema_hint):
        return {
            "milestones": [
                {
                    "name": "Backend MVP",
                    "description": "Create the backend slice.",
                    "order_index": 1,
                    "features": [
                        {
                            "title": "Create API",
                            "description": "Create a small API endpoint.",
                            "task_type": "backend",
                        }
                    ],
                }
            ],
            "assumptions": [],
            "risks": [],
        }


class FakeSpecLLM:
    async def generate_json(self, system_prompt, user_prompt, schema_hint):
        return {
            "contract_markdown": "# Validation Contract\n\nThe API exposes observable behavior.",
            "assertions": [
                {
                    "id": "A1",
                    "description": "GET /health returns status ok.",
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
            "definition_of_done": ["All required tests pass."],
        }


class AgentInterfaceTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.context = AgentContext(mission_id=uuid4(), db=Mock())
        self.input = AgentInput(instructions="Run deterministic stub.")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_each_agent_can_run(self) -> None:
        for agent in (
            PlannerAgent(llm_service=FakePlannerLLM()),
            SpecAgent(llm_service=FakeSpecLLM()),
            ResearchAgent(),
            WorkerAgent(),
            ValidatorAgent(),
            FixPlannerAgent(),
        ):
            if isinstance(agent, PlannerAgent):
                self.input.data = {"title": "Build login", "goal": "Build auth"}
            if isinstance(agent, SpecAgent):
                self.input.data = {
                    "goal": "Build auth",
                    "milestones": [{"name": "MVP"}],
                    "feature_tasks": [{"title": "Create API"}],
                }
            if isinstance(agent, WorkerAgent):
                self.context.repo_path = self.repo_path
                self.context.feature_task_id = uuid4()
                self.input.data = {
                    "title": "Create API",
                    "description": "Create a small API endpoint.",
                }
            if isinstance(agent, ValidatorAgent):
                self.context.repo_path = self.repo_path
                self.input.data = {
                    "milestone": {"id": str(uuid4())},
                    "validation_contract": {
                        "required_tests": [
                            {
                                "name": "python smoke",
                                "type": "shell",
                                "command": "python -c \"print('ok')\"",
                            }
                        ],
                    },
                }

            output = asyncio.run(agent.run(self.context, self.input))

            self.assertEqual(output.agent_type, agent.agent_type)
            self.assertEqual(output.status, "completed")
            self.assertTrue(output.summary)

    def test_default_registry_resolves_each_agent_type(self) -> None:
        registry = build_default_registry()

        for agent_type in ("fix_planner", "planner", "research", "spec", "validator", "worker"):
            agent = registry.get(agent_type)

            self.assertEqual(agent.agent_type, agent_type)
