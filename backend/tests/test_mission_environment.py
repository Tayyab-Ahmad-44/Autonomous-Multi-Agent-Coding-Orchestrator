from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.core.config import Settings
from app.services import mission_environment as env_mod
from app.services.git_service import GitService
from app.services.mission_environment import MissionEnvironmentService, mission_env_vars, venv_path_for


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mission" / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "requirements.txt").write_bytes("fastapi==0.110\n".encode("utf-16"))
    return repo


class FakeRunner:
    """Records install commands and creates the venv python so the flow proceeds."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.commands: list[list[str]] = []

    def __call__(self, command, log, *, cwd, timeout):
        self.commands.append(command)
        if "venv" in command:
            venv = Path(command[-1])
            python = env_mod._venv_python(venv)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("")
        return self.ok


def _service() -> MissionEnvironmentService:
    return MissionEnvironmentService(settings=Settings(mission_env_enabled=True))


def test_venv_lives_next_to_repo_not_inside(tmp_path):
    repo = _make_repo(tmp_path)
    assert venv_path_for(repo) == (tmp_path / "mission" / ".venv").resolve()


def test_installs_subfolder_requirements_reencoded_as_utf8(tmp_path):
    repo = _make_repo(tmp_path)
    runner = FakeRunner()
    with patch.object(env_mod, "_run", runner):
        result = _service().ensure(repo)

    assert result.status == "ready"
    assert result.manifest_dir == "backend"
    install = runner.commands[-1]
    req_copy = Path(install[install.index("-r") + 1])
    assert req_copy.read_text(encoding="utf-8") == "fastapi==0.110\n"
    assert "pytest" in install


def test_second_call_reuses_environment_until_requirements_change(tmp_path):
    repo = _make_repo(tmp_path)
    runner = FakeRunner()
    with patch.object(env_mod, "_run", runner):
        assert _service().ensure(repo).status == "ready"
        calls = len(runner.commands)
        assert _service().ensure(repo).status == "reused"
        assert len(runner.commands) == calls

        (repo / "backend" / "requirements.txt").write_text("fastapi==0.111\n", encoding="utf-8")
        assert _service().ensure(repo).status == "ready"


def test_failed_install_leaves_no_stamp(tmp_path):
    repo = _make_repo(tmp_path)
    with patch.object(env_mod, "_run", FakeRunner(ok=False)):
        result = _service().ensure(repo)
    assert result.status == "failed"
    assert mission_env_vars(repo) is None


def test_skipped_without_python_manifest(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _service().ensure(repo).status == "skipped"


def test_env_vars_put_venv_first_on_path(tmp_path):
    repo = _make_repo(tmp_path)
    with patch.object(env_mod, "_run", FakeRunner()):
        _service().ensure(repo)

    env = mission_env_vars(repo, base={"PATH": "host-bin", "PYTHONHOME": "x"})
    assert env is not None
    assert env["VIRTUAL_ENV"] == str(venv_path_for(repo))
    assert env["PATH"].startswith(str(env_mod._scripts_dir(venv_path_for(repo))) + os.pathsep)
    assert "PYTHONHOME" not in env


def test_local_excludes_keep_logs_out_of_commits(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    git = GitService()
    git.ensure_local_excludes(str(repo))
    git.ensure_local_excludes(str(repo))  # idempotent

    (repo / "logs").mkdir()
    (repo / "logs" / "app.log").write_text("noise")
    (repo / "health.py").write_text("x = 1")

    assert git.status(str(repo)).split() == ["??", "health.py"]
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count("logs/") == 1


def test_env_vars_disable_pytest_cache(tmp_path):
    repo = _make_repo(tmp_path)
    with patch.object(env_mod, "_run", FakeRunner()):
        _service().ensure(repo)
    env = mission_env_vars(repo, base={"PATH": "x"})
    assert "-p no:cacheprovider" in env["PYTEST_ADDOPTS"]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
