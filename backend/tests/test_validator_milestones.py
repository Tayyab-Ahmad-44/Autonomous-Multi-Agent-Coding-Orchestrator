"""pytest's "no tests collected" (exit 5) is deferred until the final milestone,
because the mission-wide contract's tests are often written in a later one."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AgentContext, AgentInput
from app.agents.validator import ValidatorAgent
from app.core.database import Base
from app.services import missions as mission_service
from app.services.sandbox_service import SandboxResult
from tests.factories import persist_test_repo, persist_test_user


class ExitCodeSandbox:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code

    def run_command(self, *, repo_path: str, command: str, timeout_seconds: int = 300) -> SandboxResult:
        return SandboxResult(
            command=command, repo_path=repo_path, stdout="collected 0 items", stderr="",
            exit_code=self.exit_code, duration_seconds=0.1,
        )


@pytest.fixture
def mission(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    user = persist_test_user(session_local)
    repo = persist_test_repo(session_local, user_id=user.id)
    db = session_local()
    m = mission_service.create_mission(db, owner_id=user.id, repo_id=repo.id, title="t", goal="g")
    first = mission_service.create_milestone(db, mission_id=m.id, name="Code", description="d", order_index=1)
    last = mission_service.create_milestone(db, mission_id=m.id, name="Tests", description="d", order_index=2)
    yield db, m, first, last, tmp_path
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _validate(db, mission, milestone, repo_path, exit_code):
    contract = {"required_tests": [{"name": "unit tests", "type": "pytest", "command": "pytest -q"}]}
    output = asyncio.run(
        ValidatorAgent(sandbox_service=ExitCodeSandbox(exit_code)).run(
            AgentContext(mission_id=mission.id, db=db, repo_path=repo_path),
            AgentInput(
                instructions="",
                data={
                    "validation_contract": contract,
                    "milestone": {"id": str(milestone.id), "order_index": milestone.order_index},
                },
            ),
        )
    )
    return output.data


def test_no_tests_collected_is_deferred_before_final_milestone(mission):
    db, m, first, _last, repo_path = mission
    data = _validate(db, m, first, repo_path, exit_code=5)
    assert data["passed"] is True
    assert data["skipped"][0]["reason"].startswith("pytest collected no tests yet")


def test_no_tests_collected_fails_on_final_milestone(mission):
    db, m, _first, last, repo_path = mission
    assert _validate(db, m, last, repo_path, exit_code=5)["passed"] is False


def test_real_test_failure_still_fails_early_milestone(mission):
    db, m, first, _last, repo_path = mission
    assert _validate(db, m, first, repo_path, exit_code=1)["passed"] is False
