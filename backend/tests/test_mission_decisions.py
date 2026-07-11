from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, PlannerAgent, WorkerAgent
from app.core.config import Settings
from app.core.database import Base
from app.models import FeatureTaskType
from app.services import missions as mission_service
from app.services.codex_service import CodexResult
from tests.factories import persist_test_repo, persist_test_user


class FakeCodexService:
    """Duck-typed stand-in for CodexService; never shells out to the real Codex CLI."""

    def __init__(self, result: CodexResult) -> None:
        self._result = result
        self.calls: list[dict[str, str]] = []

    def run_codex_task(self, *, repo_path: str, task_prompt: str) -> CodexResult:
        self.calls.append({"repo_path": repo_path, "task_prompt": task_prompt})
        return self._result


class FakeGitService:
    """Duck-typed stand-in for GitService; avoids real subprocess/git dependence in tests."""

    def __init__(self, *, diff: str = "", status: str = "", is_repo: bool = True) -> None:
        self._diff = diff
        self._status = status
        self._is_repo = is_repo

    def is_git_repo(self, path: str) -> bool:
        return self._is_repo

    def current_branch(self, path: str) -> str:
        return "main"

    def checkout_branch(self, path: str, branch_name: str) -> str:
        return f"checked out {branch_name}"

    def create_branch(self, path: str, branch_name: str) -> str:
        return f"created {branch_name}"

    def diff(self, path: str) -> str:
        return self._diff

    def status(self, path: str) -> str:
        return self._status

    def commit_all(self, path: str, message: str) -> str:
        return "committed"

    def get_latest_commit(self, path: str) -> str:
        return "abc123"


class FakeDecisionLLM:
    """Mirrors FakePlannerLLM/FakeSpecLLM in test_agents.py: a fake for the generate_json Protocol."""

    def __init__(self, decisions: list[dict[str, str]]) -> None:
        self._decisions = decisions
        self.calls: list[dict[str, object]] = []

    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "schema_hint": schema_hint}
        )
        return {"decisions": self._decisions}


class BrokenDecisionLLM:
    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        raise RuntimeError("decision extraction boom")


class FakePlannerLLMCapturingPrompt:
    def __init__(self) -> None:
        self.captured_user_prompt: str = ""

    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        self.captured_user_prompt = user_prompt
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


def _successful_codex_result(repo_path: Path) -> CodexResult:
    return CodexResult(
        command=["codex-test", "exec", "prompt"],
        repo_path=str(repo_path),
        stdout="Implemented the requested change.",
        stderr="",
        exit_code=0,
        duration_seconds=1.0,
    )


class MissionDecisionMemoryTests(TestCase):
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
        self.user = persist_test_user(self.session_local)
        self.repo = persist_test_repo(self.session_local, user_id=self.user.id)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _create_feature_task(self, *, title: str, description: str, task_type: FeatureTaskType):
        with self.session_local() as db:
            mission = mission_service.create_mission(
                db, owner_id=self.user.id, repo_id=self.repo.id, title="Build login system", goal="Build auth"
            )
            milestone = mission_service.create_milestone(
                db,
                mission_id=mission.id,
                name="Backend MVP",
                description="Create backend slice.",
                order_index=1,
            )
            feature_task = mission_service.create_feature_task(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                title=title,
                description=description,
                task_type=task_type,
                assigned_agent_type="worker",
            )
            return mission.id, feature_task.id

    # -- write path ---------------------------------------------------------

    def test_worker_extracts_and_stores_decisions_after_successful_codex_run(self) -> None:
        mission_id, feature_task_id = self._create_feature_task(
            title="Add JWT auth",
            description="Implement login with JWT.",
            task_type=FeatureTaskType.backend,
        )

        fake_codex = FakeCodexService(_successful_codex_result(self.repo_path))
        fake_git = FakeGitService(diff="diff --git a/auth.py b/auth.py\n+jwt logic", status=" M auth.py")
        fake_decision_llm = FakeDecisionLLM([{"key": "auth_scheme", "value": "JWT with refresh tokens"}])
        worker = WorkerAgent(
            codex_service=fake_codex,
            git_service=fake_git,
            settings=Settings(codex_enabled=True),
            decision_llm_service=fake_decision_llm,
        )

        with self.session_local() as db:
            context = AgentContext(
                mission_id=mission_id,
                db=db,
                feature_task_id=feature_task_id,
                repo_path=self.repo_path,
            )
            output = asyncio.run(
                worker.run(
                    context,
                    AgentInput(
                        instructions="Implement the task.",
                        data={"title": "Add JWT auth", "description": "Implement login with JWT.", "task_type": "backend"},
                    ),
                )
            )

        self.assertEqual(output.status, "completed")
        self.assertEqual(len(fake_decision_llm.calls), 1)
        self.assertIn("Add JWT auth", fake_decision_llm.calls[0]["user_prompt"])
        self.assertIn("diff --git", fake_decision_llm.calls[0]["user_prompt"])

        with self.session_local() as db:
            decisions = mission_service.list_mission_decisions(db, mission_id)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].key, "auth_scheme")
        self.assertEqual(decisions[0].value, "JWT with refresh tokens")
        self.assertEqual(decisions[0].source_task_id, feature_task_id)

    def test_no_extraction_when_task_produces_no_diff(self) -> None:
        mission_id, feature_task_id = self._create_feature_task(
            title="Investigate flaky test",
            description="Research only, no code changes expected.",
            task_type=FeatureTaskType.research,
        )

        fake_codex = FakeCodexService(_successful_codex_result(self.repo_path))
        fake_git = FakeGitService(diff="", status="")
        fake_decision_llm = FakeDecisionLLM([{"key": "should_not_appear", "value": "should_not_appear"}])
        worker = WorkerAgent(
            codex_service=fake_codex,
            git_service=fake_git,
            settings=Settings(codex_enabled=True),
            decision_llm_service=fake_decision_llm,
        )

        with self.session_local() as db:
            context = AgentContext(
                mission_id=mission_id,
                db=db,
                feature_task_id=feature_task_id,
                repo_path=self.repo_path,
            )
            asyncio.run(
                worker.run(
                    context,
                    AgentInput(instructions="Investigate.", data={"title": "Investigate flaky test", "description": "..."}),
                )
            )

        self.assertEqual(fake_decision_llm.calls, [])
        with self.session_local() as db:
            self.assertEqual(mission_service.list_mission_decisions(db, mission_id), [])

    def test_extraction_failure_does_not_fail_the_task(self) -> None:
        mission_id, feature_task_id = self._create_feature_task(
            title="Add JWT auth",
            description="Implement login with JWT.",
            task_type=FeatureTaskType.backend,
        )

        fake_codex = FakeCodexService(_successful_codex_result(self.repo_path))
        fake_git = FakeGitService(diff="diff --git a/auth.py b/auth.py\n+jwt logic", status=" M auth.py")
        worker = WorkerAgent(
            codex_service=fake_codex,
            git_service=fake_git,
            settings=Settings(codex_enabled=True),
            decision_llm_service=BrokenDecisionLLM(),
        )

        with self.session_local() as db:
            context = AgentContext(
                mission_id=mission_id,
                db=db,
                feature_task_id=feature_task_id,
                repo_path=self.repo_path,
            )
            output = asyncio.run(
                worker.run(
                    context,
                    AgentInput(
                        instructions="Implement the task.",
                        data={"title": "Add JWT auth", "description": "Implement login with JWT."},
                    ),
                )
            )

        self.assertEqual(output.status, "completed")
        with self.session_local() as db:
            self.assertEqual(mission_service.list_mission_decisions(db, mission_id), [])

    # -- read path ------------------------------------------------------------

    def test_planner_prompt_includes_prior_mission_decisions(self) -> None:
        with self.session_local() as db:
            mission = mission_service.create_mission(
                db, owner_id=self.user.id, repo_id=self.repo.id, title="Build app", goal="Build a web app"
            )
            mission_service.create_mission_decision(
                db,
                mission_id=mission.id,
                key="auth_scheme",
                value="JWT with refresh tokens",
            )
            mission_id = mission.id

        fake_planner_llm = FakePlannerLLMCapturingPrompt()
        with self.session_local() as db:
            asyncio.run(
                mission_service.run_planning_for_mission(
                    db,
                    mission_id,
                    planner_agent=PlannerAgent(llm_service=fake_planner_llm),
                )
            )

        self.assertIn("Prior decisions in this mission", fake_planner_llm.captured_user_prompt)
        self.assertIn("auth_scheme: JWT with refresh tokens", fake_planner_llm.captured_user_prompt)

    # -- full path: a later task's worker prompt includes an earlier task's decision -----

    def test_second_worker_task_prompt_includes_decision_from_first_task(self) -> None:
        with self.session_local() as db:
            mission = mission_service.create_mission(
                db, owner_id=self.user.id, repo_id=self.repo.id, title="Build app", goal="Build a web app"
            )
            milestone = mission_service.create_milestone(
                db,
                mission_id=mission.id,
                name="MVP",
                description="Backend and frontend slice.",
                order_index=1,
            )
            task1 = mission_service.create_feature_task(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                title="Add auth",
                description="Implement authentication.",
                task_type=FeatureTaskType.backend,
                assigned_agent_type="worker",
            )
            task2 = mission_service.create_feature_task(
                db,
                mission_id=mission.id,
                milestone_id=milestone.id,
                title="Add profile page",
                description="Implement the user profile page.",
                task_type=FeatureTaskType.frontend,
                assigned_agent_type="worker",
            )
            mission_id, task1_id, task2_id = mission.id, task1.id, task2.id

        fake_git = FakeGitService(diff="diff --git a/auth.py b/auth.py\n+jwt logic", status=" M auth.py")

        worker1 = WorkerAgent(
            codex_service=FakeCodexService(_successful_codex_result(self.repo_path)),
            git_service=fake_git,
            settings=Settings(codex_enabled=True),
            decision_llm_service=FakeDecisionLLM([{"key": "auth_scheme", "value": "JWT with refresh tokens"}]),
        )
        with self.session_local() as db:
            context1 = AgentContext(mission_id=mission_id, db=db, feature_task_id=task1_id, repo_path=self.repo_path)
            asyncio.run(
                worker1.run(
                    context1,
                    AgentInput(
                        instructions="Implement the task.",
                        data={"title": "Add auth", "description": "Implement authentication."},
                    ),
                )
            )

        fake_codex_2 = FakeCodexService(_successful_codex_result(self.repo_path))
        worker2 = WorkerAgent(
            codex_service=fake_codex_2,
            git_service=fake_git,
            settings=Settings(codex_enabled=True),
            decision_llm_service=FakeDecisionLLM([]),
        )
        with self.session_local() as db:
            context2 = AgentContext(mission_id=mission_id, db=db, feature_task_id=task2_id, repo_path=self.repo_path)
            asyncio.run(
                worker2.run(
                    context2,
                    AgentInput(
                        instructions="Implement the task.",
                        data={"title": "Add profile page", "description": "Implement the user profile page."},
                    ),
                )
            )

        self.assertEqual(len(fake_codex_2.calls), 1)
        prompt = fake_codex_2.calls[0]["task_prompt"]
        self.assertIn("Prior decisions in this mission", prompt)
        self.assertIn("auth_scheme: JWT with refresh tokens", prompt)
