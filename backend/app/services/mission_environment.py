"""Per-mission Python environment.

Validators and Codex used to run the target repo's tests with whatever Python
was on the host PATH, without the repo's dependencies. Tests then failed on
imports and fix tasks "fixed" that by rewriting unrelated code. Each mission
now gets its own virtualenv with the repo's requirements installed.

Layout: the venv lives next to the clone, never inside it, so it can't be
committed:

    {WORKSPACE_ROOT}/missions/{mission_id}/repo   <- git clone
    {WORKSPACE_ROOT}/missions/{mission_id}/.venv  <- this environment
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.repo_analysis_service import _find_manifest_dir, _read_text

_STAMP_FILE = ".orchestrator-env-stamp"
_REQUIREMENTS_COPY = ".orchestrator-requirements.txt"
_ALWAYS_INSTALL = ("pytest",)


@dataclass(slots=True)
class EnvironmentResult:
    status: str  # "skipped" | "reused" | "ready" | "failed"
    venv_path: str | None = None
    manifest_dir: str | None = None
    log: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def venv_path_for(repo_path: str | Path) -> Path:
    return Path(repo_path).expanduser().resolve().parent / ".venv"


def _scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv: Path) -> Path:
    return _scripts_dir(venv) / ("python.exe" if os.name == "nt" else "python")


def mission_env_vars(repo_path: str | Path, base: dict[str, str] | None = None) -> dict[str, str] | None:
    """Environment variables that activate the mission venv, or None if the
    mission has no ready environment (callers then inherit the host env)."""
    venv = venv_path_for(repo_path)
    if not (venv / _STAMP_FILE).exists():
        return None
    env = dict(base if base is not None else os.environ)
    env.pop("PYTHONHOME", None)
    env["VIRTUAL_ENV"] = str(venv)
    # Cache dirs created inside Codex's Windows sandbox can end up unreadable
    # for later runs ("Access is denied" during collection); mission runs
    # don't need them.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + " -p no:cacheprovider").strip()
    path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
    env[path_key] = str(_scripts_dir(venv)) + os.pathsep + env.get(path_key, "")
    return env


class MissionEnvironmentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def ensure(self, repo_path: str | Path) -> EnvironmentResult:
        started = time.monotonic()
        repo = Path(repo_path).expanduser().resolve()
        if not self._settings.mission_env_enabled:
            return EnvironmentResult(status="skipped", log=["MISSION_ENV_ENABLED=false"])

        manifest_dir = _find_manifest_dir(repo, ("requirements.txt", "pyproject.toml"))
        if manifest_dir is None:
            return EnvironmentResult(status="skipped", log=["No Python manifest found."])

        venv = venv_path_for(repo)
        rel_dir = manifest_dir.relative_to(repo).as_posix() or "."
        fingerprint = _fingerprint(manifest_dir, self._settings.mission_python_version)
        stamp = venv / _STAMP_FILE
        if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == fingerprint:
            return EnvironmentResult(status="reused", venv_path=str(venv), manifest_dir=rel_dir)

        log: list[str] = []
        ok = self._create_venv(venv, log) and self._install(venv, manifest_dir, log)
        if ok:
            stamp.write_text(fingerprint, encoding="utf-8")
        elif stamp.exists():
            stamp.unlink()
        return EnvironmentResult(
            status="ready" if ok else "failed",
            venv_path=str(venv),
            manifest_dir=rel_dir,
            log=log,
            duration_seconds=time.monotonic() - started,
        )

    def _create_venv(self, venv: Path, log: list[str]) -> bool:
        if _venv_python(venv).exists():
            return True
        uv = shutil.which("uv")
        if uv:
            command = [uv, "venv", "--python", self._settings.mission_python_version, str(venv)]
        else:
            command = [sys.executable, "-m", "venv", str(venv)]
        return _run(command, log, cwd=venv.parent, timeout=300)

    def _install(self, venv: Path, manifest_dir: Path, log: list[str]) -> bool:
        python = str(_venv_python(venv))
        uv = shutil.which("uv")
        pip = [uv, "pip", "install", "--python", python] if uv else [python, "-m", "pip", "install"]

        args: list[str] = []
        requirements = manifest_dir / "requirements.txt"
        if requirements.is_file():
            # Re-encode as UTF-8: Windows tools often write UTF-16 requirements
            # files, which installers can't parse.
            normalized = venv / _REQUIREMENTS_COPY
            normalized.write_text(_read_text(requirements) or "", encoding="utf-8")
            args += ["-r", str(normalized)]
        elif (manifest_dir / "pyproject.toml").is_file():
            args += ["-e", str(manifest_dir)]
        args += list(_ALWAYS_INSTALL)
        return _run(
            [*pip, *args],
            log,
            cwd=manifest_dir,
            timeout=self._settings.mission_env_install_timeout_seconds,
        )


def _fingerprint(manifest_dir: Path, python_version: str) -> str:
    digest = hashlib.sha256(python_version.encode())
    for name in ("requirements.txt", "pyproject.toml"):
        path = manifest_dir / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(command: list[str], log: list[str], *, cwd: Path, timeout: int) -> bool:
    log.append("$ " + " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.append(f"failed: {exc}")
        return False
    output = (completed.stdout + completed.stderr).strip()
    if output:
        log.append(output[-4000:])
    if completed.returncode != 0:
        log.append(f"exit code {completed.returncode}")
    return completed.returncode == 0
