from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest import TestCase

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import (
    AgentContext,
    AgentInput,
    MemoryPromoterAgent,
    PlannerAgent,
    SpecAgent,
    WorkerAgent,
)
from app.core.config import Settings
from app.core.database import Base
from app.models import FeatureTaskType, MemoryScope, MemorySource, MemoryStatus
from app.services import memory as memory_service
from app.services import missions as mission_service
from app.services.codex_service import CodexResult
from tests.factories import persist_test_repo, persist_test_user


class FakePromoterLLM:
    """Duck-typed stand-in for the generate_json Protocol, as in test_mission_decisions.py."""

    def __init__(self, promotions: list[dict[str, str]]) -> None:
        self._promotions = promotions
        self.calls: list[dict[str, object]] = []

    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "schema_hint": schema_hint}
        )
        return {"promotions": self._promotions}


class BrokenPromoterLLM:
    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        raise RuntimeError("promotion boom")


class FakePromptCapturingLLM:
    """Captures the user prompt and returns a canned plan or contract, depending on what is asked."""

    def __init__(self, response: dict) -> None:
        self._response = response
        self.captured_user_prompt = ""

    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        self.captured_user_prompt = user_prompt
        return self._response


class FakeCodexService:
    def __init__(self, result: CodexResult) -> None:
        self._result = result
        self.calls: list[dict[str, str]] = []

    def run_codex_task(self, *, repo_path: str, task_prompt: str) -> CodexResult:
        self.calls.append({"repo_path": repo_path, "task_prompt": task_prompt})
        return self._result


class FakeGitService:
    def __init__(self, *, diff: str = "", status: str = "") -> None:
        self._diff = diff
        self._status = status

    def is_git_repo(self, path: str) -> bool:
        return True

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
    def __init__(self, decisions: list[dict[str, str]]) -> None:
        self._decisions = decisions

    async def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: dict) -> dict:
        return {"decisions": self._decisions}


_PLAN_RESPONSE = {
    "milestones": [
        {
            "name": "Backend MVP",
            "description": "Create the backend slice.",
            "order_index": 1,
            "features": [
                {"title": "Create API", "description": "Create an endpoint.", "task_type": "backend"}
            ],
        }
    ],
    "assumptions": [],
    "risks": [],
}

_CONTRACT_RESPONSE = {
    "contract_markdown": "# Contract",
    "assertions": [{"id": "A1", "description": "Endpoint responds.", "validation_method": "unit_test"}],
    "required_tests": [{"name": "api test", "type": "pytest", "command": "pytest"}],
    "definition_of_done": [],
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


class RepoMemoryTestBase(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # SQLite ignores foreign keys unless asked. Without this the delete-semantics these tests
        # exist to pin - owner columns CASCADE, provenance columns SET NULL - are never exercised,
        # and the tests would pass against a schema that silently orphans rows in Postgres.
        @event.listens_for(self.engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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

    def _create_mission(self, *, title: str = "Build app", goal: str = "Build a web app"):
        with self.session_local() as db:
            mission = mission_service.create_mission(
                db, owner_id=self.user.id, repo_id=self.repo.id, title=title, goal=goal
            )
            return mission.id

    def _create_milestone_and_task(self, mission_id):
        with self.session_local() as db:
            milestone = mission_service.create_milestone(
                db,
                mission_id=mission_id,
                name="Backend MVP",
                description="Create the backend slice.",
                order_index=1,
            )
            feature_task = mission_service.create_feature_task(
                db,
                mission_id=mission_id,
                milestone_id=milestone.id,
                title="Add auth",
                description="Implement authentication.",
                task_type=FeatureTaskType.backend,
                assigned_agent_type="worker",
            )
            return milestone.id, feature_task.id


class MemorySupersessionTests(RepoMemoryTestBase):
    def test_recording_the_same_key_supersedes_the_old_value_and_keeps_it(self) -> None:
        with self.session_local() as db:
            first = memory_service.record_memory(
                db,
                scope=MemoryScope.repo,
                owner_id=self.repo.id,
                key="auth_scheme",
                value="JWT with refresh tokens",
            )
            second = memory_service.record_memory(
                db,
                scope=MemoryScope.repo,
                owner_id=self.repo.id,
                key="auth_scheme",
                value="OAuth2 via Auth0",
            )

            active = memory_service.list_memories(db, scope=MemoryScope.repo, owner_id=self.repo.id)
            retired = memory_service.get_memory(db, first.id)

            self.assertEqual([m.value for m in active], ["OAuth2 via Auth0"])
            self.assertEqual(retired.status, MemoryStatus.superseded)
            self.assertEqual(retired.superseded_by_id, second.id)
            self.assertIsNotNone(retired.superseded_at)

    def test_the_same_key_in_different_scopes_does_not_collide(self) -> None:
        mission_id = self._create_mission()
        with self.session_local() as db:
            memory_service.record_memory(
                db, scope=MemoryScope.repo, owner_id=self.repo.id, key="test_framework", value="unittest"
            )
            memory_service.record_memory(
                db,
                scope=MemoryScope.user,
                owner_id=self.user.id,
                key="test_framework",
                value="pytest",
                source=MemorySource.user_stated,
            )
            memory_service.record_memory(
                db, scope=MemoryScope.mission, owner_id=mission_id, key="test_framework", value="pytest"
            )

            self.assertEqual(
                [m.value for m in mission_service.list_repo_memories(db, self.repo.id)], ["unittest"]
            )
            self.assertEqual(
                [m.value for m in mission_service.list_user_preferences(db, self.user.id)], ["pytest"]
            )
            self.assertEqual(
                [m.value for m in mission_service.list_mission_decisions(db, mission_id)], ["pytest"]
            )

    def test_a_later_task_revising_a_decision_replaces_it_rather_than_appending(self) -> None:
        mission_id = self._create_mission()
        with self.session_local() as db:
            mission_service.create_mission_decision(
                db, mission_id=mission_id, key="auth_scheme", value="session cookies"
            )
            mission_service.create_mission_decision(
                db, mission_id=mission_id, key="auth_scheme", value="JWT"
            )
            decisions = mission_service.list_mission_decisions(db, mission_id)

        self.assertEqual([(d.key, d.value) for d in decisions], [("auth_scheme", "JWT")])


class PromotionTests(RepoMemoryTestBase):
    def _promote(self, promoter_llm, *, decisions: list[tuple[str, str]]):
        mission_id = self._create_mission()
        milestone_id, task_id = self._create_milestone_and_task(mission_id)
        with self.session_local() as db:
            for key, value in decisions:
                mission_service.create_mission_decision(
                    db, mission_id=mission_id, key=key, value=value, source_task_id=task_id
                )

        with self.session_local() as db:
            promoted = asyncio.run(
                mission_service.promote_repo_memories_for_milestone(
                    db,
                    mission_id,
                    milestone_id,
                    memory_promoter_agent=MemoryPromoterAgent(llm_service=promoter_llm),
                )
            )
        return mission_id, milestone_id, promoted

    def test_passed_milestone_promotes_durable_facts_to_repo_memory_with_provenance(self) -> None:
        promoter = FakePromoterLLM([{"key": "auth_scheme", "value": "JWT with refresh tokens"}])
        mission_id, milestone_id, promoted = self._promote(
            promoter, decisions=[("auth_scheme", "JWT with refresh tokens")]
        )

        self.assertEqual(len(promoted), 1)
        with self.session_local() as db:
            repo_memories = mission_service.list_repo_memories(db, self.repo.id)

        self.assertEqual(len(repo_memories), 1)
        memory = repo_memories[0]
        self.assertEqual(memory.key, "auth_scheme")
        self.assertEqual(memory.scope, MemoryScope.repo)
        self.assertEqual(memory.repo_id, self.repo.id)
        self.assertEqual(memory.source_mission_id, mission_id)
        self.assertEqual(memory.source_milestone_id, milestone_id)

    def test_promoter_sees_existing_repo_memory_so_it_can_supersede(self) -> None:
        with self.session_local() as db:
            memory_service.record_memory(
                db,
                scope=MemoryScope.repo,
                owner_id=self.repo.id,
                key="auth_scheme",
                value="JWT with refresh tokens",
            )

        promoter = FakePromoterLLM([{"key": "auth_scheme", "value": "OAuth2 via Auth0"}])
        self._promote(promoter, decisions=[("auth_scheme", "OAuth2 via Auth0")])

        self.assertIn("auth_scheme: JWT with refresh tokens", promoter.calls[0]["user_prompt"])
        with self.session_local() as db:
            repo_memories = mission_service.list_repo_memories(db, self.repo.id)

        self.assertEqual([m.value for m in repo_memories], ["OAuth2 via Auth0"])

    def test_promoting_nothing_is_allowed(self) -> None:
        _, _, promoted = self._promote(FakePromoterLLM([]), decisions=[("tmp_var_name", "user_row")])

        self.assertEqual(promoted, [])
        with self.session_local() as db:
            self.assertEqual(mission_service.list_repo_memories(db, self.repo.id), [])

    def test_promotion_failure_does_not_raise(self) -> None:
        _, _, promoted = self._promote(BrokenPromoterLLM(), decisions=[("auth_scheme", "JWT")])

        self.assertEqual(promoted, [])
        with self.session_local() as db:
            self.assertEqual(mission_service.list_repo_memories(db, self.repo.id), [])

    def test_no_llm_call_when_the_mission_recorded_no_decisions(self) -> None:
        mission_id = self._create_mission()
        milestone_id, _ = self._create_milestone_and_task(mission_id)
        promoter = FakePromoterLLM([{"key": "should_not_appear", "value": "x"}])

        with self.session_local() as db:
            promoted = asyncio.run(
                mission_service.promote_repo_memories_for_milestone(
                    db,
                    mission_id,
                    milestone_id,
                    memory_promoter_agent=MemoryPromoterAgent(llm_service=promoter),
                )
            )

        self.assertEqual(promoted, [])
        self.assertEqual(promoter.calls, [])

    def test_promoted_repo_memory_survives_deletion_of_the_mission_that_taught_it(self) -> None:
        promoter = FakePromoterLLM([{"key": "auth_scheme", "value": "JWT with refresh tokens"}])
        mission_id, _, _ = self._promote(promoter, decisions=[("auth_scheme", "JWT with refresh tokens")])

        with self.session_local() as db:
            mission = mission_service.get_mission(db, mission_id)
            mission_service.delete_mission(db, mission)

        with self.session_local() as db:
            repo_memories = mission_service.list_repo_memories(db, self.repo.id)
            self.assertEqual([m.key for m in repo_memories], ["auth_scheme"])
            self.assertIsNone(repo_memories[0].source_mission_id)
            self.assertEqual(mission_service.list_mission_decisions(db, mission_id), [])


class InjectionTests(RepoMemoryTestBase):
    def _seed_repo_and_user_memory(self) -> None:
        with self.session_local() as db:
            memory_service.record_memory(
                db,
                scope=MemoryScope.repo,
                owner_id=self.repo.id,
                key="test_framework",
                value="unittest",
            )
            memory_service.record_memory(
                db,
                scope=MemoryScope.user,
                owner_id=self.user.id,
                key="test_framework",
                value="pytest, never unittest",
                source=MemorySource.user_stated,
            )

    def test_planner_prompt_carries_repo_memory_user_preferences_and_the_precedence_rule(self) -> None:
        self._seed_repo_and_user_memory()
        mission_id = self._create_mission()
        planner_llm = FakePromptCapturingLLM(_PLAN_RESPONSE)

        with self.session_local() as db:
            asyncio.run(
                mission_service.run_planning_for_mission(
                    db, mission_id, planner_agent=PlannerAgent(llm_service=planner_llm)
                )
            )

        prompt = planner_llm.captured_user_prompt
        self.assertIn("What we know about this repo", prompt)
        self.assertIn("test_framework: unittest", prompt)
        self.assertIn("Your preferences", prompt)
        self.assertIn("test_framework: pytest, never unittest", prompt)
        # The conflict is surfaced, not resolved: both values are present, with a rule for the model.
        self.assertIn("take precedence for new code", prompt)

    def test_spec_prompt_carries_repo_memory(self) -> None:
        self._seed_repo_and_user_memory()
        mission_id = self._create_mission()
        self._create_milestone_and_task(mission_id)
        spec_llm = FakePromptCapturingLLM(_CONTRACT_RESPONSE)

        with self.session_local() as db:
            asyncio.run(
                mission_service.generate_validation_contract(
                    db, mission_id, spec_agent=SpecAgent(llm_service=spec_llm)
                )
            )

        prompt = spec_llm.captured_user_prompt
        self.assertIn("What we know about this repo", prompt)
        self.assertIn("test_framework: unittest", prompt)
        self.assertIn("test_framework: pytest, never unittest", prompt)

    def test_worker_prompt_carries_all_three_tiers(self) -> None:
        self._seed_repo_and_user_memory()
        mission_id = self._create_mission()
        _, task_id = self._create_milestone_and_task(mission_id)
        with self.session_local() as db:
            mission_service.create_mission_decision(
                db, mission_id=mission_id, key="error_shape", value="RFC7807 problem+json"
            )

        codex = FakeCodexService(_successful_codex_result(self.repo_path))
        worker = WorkerAgent(
            codex_service=codex,
            git_service=FakeGitService(diff="", status=""),
            settings=Settings(codex_enabled=True),
            decision_llm_service=FakeDecisionLLM([]),
        )

        with self.session_local() as db:
            asyncio.run(
                worker.run(
                    AgentContext(
                        mission_id=mission_id,
                        db=db,
                        feature_task_id=task_id,
                        repo_path=self.repo_path,
                    ),
                    AgentInput(
                        instructions="Implement the task.",
                        data={"title": "Add auth", "description": "Implement authentication."},
                    ),
                )
            )

        prompt = codex.calls[0]["task_prompt"]
        self.assertIn("Prior decisions in this mission", prompt)
        self.assertIn("error_shape: RFC7807 problem+json", prompt)
        self.assertIn("What we know about this repo", prompt)
        self.assertIn("test_framework: unittest", prompt)
        self.assertIn("Your preferences", prompt)
        self.assertIn("test_framework: pytest, never unittest", prompt)


class CrossMissionTests(RepoMemoryTestBase):
    def test_a_fact_promoted_in_one_mission_reaches_the_next_missions_planner(self) -> None:
        # Mission 1: a task records a decision, and its milestone passes validation.
        mission_one = self._create_mission(title="Add auth", goal="Add authentication")
        milestone_id, task_id = self._create_milestone_and_task(mission_one)
        with self.session_local() as db:
            mission_service.create_mission_decision(
                db,
                mission_id=mission_one,
                key="auth_scheme",
                value="JWT with refresh tokens",
                source_task_id=task_id,
            )
        with self.session_local() as db:
            asyncio.run(
                mission_service.promote_repo_memories_for_milestone(
                    db,
                    mission_one,
                    milestone_id,
                    memory_promoter_agent=MemoryPromoterAgent(
                        llm_service=FakePromoterLLM(
                            [{"key": "auth_scheme", "value": "JWT with refresh tokens"}]
                        )
                    ),
                )
            )

        # Mission 2 is a brand new mission on the same repo. It never saw mission 1's decisions.
        mission_two = self._create_mission(title="Add profile page", goal="Add a user profile page")
        planner_llm = FakePromptCapturingLLM(_PLAN_RESPONSE)
        with self.session_local() as db:
            asyncio.run(
                mission_service.run_planning_for_mission(
                    db, mission_two, planner_agent=PlannerAgent(llm_service=planner_llm)
                )
            )

        prompt = planner_llm.captured_user_prompt
        self.assertIn("What we know about this repo", prompt)
        self.assertIn("auth_scheme: JWT with refresh tokens", prompt)
        # Mission 1's decisions are not leaked as mission 2's own decisions.
        self.assertNotIn("Prior decisions in this mission", prompt)
