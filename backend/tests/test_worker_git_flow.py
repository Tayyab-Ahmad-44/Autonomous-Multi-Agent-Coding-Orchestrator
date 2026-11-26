"""Worker git flow against a real git repo: task work must land on the
mission branch (which open-pr pushes), and a Codex run that changes nothing
must not count as a completed coding task."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput, WorkerAgent
from app.core.config import Settings
from app.core.database import Base
from app.models import FeatureTask, FeatureTaskStatus, FeatureTaskType
from app.services import missions as mission_service
from app.services.codex_service import CodexResult
from app.services.git_service import GitService
from tests.factories import persist_test_repo, persist_test_user


class WritingCodex:
    """Fake Codex that optionally writes a file, like a real coding run."""

    def __init__(self, filename: str | None, stdout: str = "done") -> None:
        self.filename = filename
        self.stdout = stdout

    def run_codex_task(self, *, repo_path: str, task_prompt: str) -> CodexResult:
        if self.filename:
            (Path(repo_path) / self.filename).write_text("print('hi')\n", encoding="utf-8")
        return CodexResult(
            command=["codex", "exec", task_prompt],
            repo_path=repo_path,
            stdout=self.stdout,
            stderr="",
            exit_code=0,
            duration_seconds=0.1,
        )


class NoDecisions:
    async def generate_json(self, system_prompt, user_prompt, schema_hint):
        return {"decisions": []}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def env(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    user = persist_test_user(session_local)
    repo_row = persist_test_repo(session_local, user_id=user.id)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    with session_local() as db:
        mission = mission_service.create_mission(
            db, owner_id=user.id, repo_id=repo_row.id, title="Health", goal="Add /health"
        )
        milestone = mission_service.create_milestone(
            db, mission_id=mission.id, name="M1", description="d", order_index=1
        )
        mission_id, milestone_id = mission.id, milestone.id
    _git(repo, "checkout", "-q", "-b", f"mission/{str(mission_id)[:8]}")
    yield session_local, repo, mission_id, milestone_id
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _run_task(session_local, repo, mission_id, milestone_id, codex, title, task_type=FeatureTaskType.backend):
    with session_local() as db:
        task = mission_service.create_feature_task(
            db, mission_id=mission_id, milestone_id=milestone_id, title=title,
            description=title, task_type=task_type, assigned_agent_type="worker",
        )
        worker = WorkerAgent(
            codex_service=codex,
            git_service=GitService(),
            settings=Settings(codex_enabled=True, auto_commit=True),
            decision_llm_service=NoDecisions(),
        )
        output = asyncio.run(
            worker.run(
                AgentContext(mission_id=mission_id, db=db, feature_task_id=task.id, repo_path=repo),
                AgentInput(instructions="", data={"title": title, "description": title, "task_type": task_type.value}),
            )
        )
        status = db.get(FeatureTask, task.id).status
    return output, status


def test_task_commits_are_merged_into_mission_branch(env):
    session_local, repo, mission_id, milestone_id = env
    mission_branch = f"mission/{str(mission_id)[:8]}"

    out1, _ = _run_task(session_local, repo, mission_id, milestone_id, WritingCodex("health.py"), "Add route")
    out2, _ = _run_task(session_local, repo, mission_id, milestone_id, WritingCodex("test_health.py"), "Add test")

    assert out1.status == "completed" and out2.status == "completed"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == mission_branch
    files = _git(repo, "ls-tree", "--name-only", mission_branch).splitlines()
    assert {"health.py", "test_health.py"} <= set(files)
    assert GitService().commits_ahead(str(repo), "main", mission_branch) == 2


def test_codex_run_without_changes_fails_coding_task(env):
    session_local, repo, mission_id, milestone_id = env

    output, status = _run_task(
        session_local, repo, mission_id, milestone_id,
        WritingCodex(None, stdout="Blocked: sandbox helper missing"), "Add route",
    )

    assert output.status == "failed"
    assert status == FeatureTaskStatus.failed
    assert "without changing any files" in output.summary
    assert "Blocked" in output.summary


def test_research_task_without_changes_still_completes(env):
    session_local, repo, mission_id, milestone_id = env

    output, status = _run_task(
        session_local, repo, mission_id, milestone_id, WritingCodex(None), "Investigate", FeatureTaskType.research,
    )

    assert output.status == "completed"
    assert status == FeatureTaskStatus.completed


def test_no_changes_but_codex_confirms_done_completes(env):
    session_local, repo, mission_id, milestone_id = env

    output, status = _run_task(
        session_local, repo, mission_id, milestone_id,
        WritingCodex(None, stdout="Test already exists and passes.\n\n**STATUS: DONE**"), "Write test",
        FeatureTaskType.test,
    )

    assert output.status == "completed"
    assert status == FeatureTaskStatus.completed


def test_no_changes_and_codex_blocked_fails(env):
    session_local, repo, mission_id, milestone_id = env

    output, _ = _run_task(
        session_local, repo, mission_id, milestone_id,
        WritingCodex(None, stdout="Sandbox helper missing.\nSTATUS: BLOCKED"), "Write test",
        FeatureTaskType.test,
    )

    assert output.status == "failed"
