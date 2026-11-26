from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.mission_environment import mission_env_vars


@dataclass(slots=True)
class CodexResult:
    command: list[str]
    repo_path: str
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    timed_out: bool = False


class CodexService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _codex_env(self, working_dir: Path) -> dict[str, str] | None:
        env = mission_env_vars(working_dir)
        if self._settings.codex_auth == "api_key":
            if not self._settings.openai_api_key:
                raise ValueError("CODEX_AUTH=api_key requires OPENAI_API_KEY.")
            env = _with_api_key(env, self._settings.openai_api_key)
        return env

    def run_codex_task(
        self,
        repo_path: str,
        task_prompt: str,
        timeout_seconds: int = 1800,
    ) -> CodexResult:
        normalized_prompt = task_prompt.strip()
        if not normalized_prompt:
            raise ValueError("Codex task prompt must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        working_dir = Path(repo_path).expanduser().resolve()
        if not working_dir.exists() or not working_dir.is_dir():
            raise ValueError(f"repo_path must be an existing directory: {repo_path}")

        command = _codex_command(
            self._settings.codex_command,
            normalized_prompt,
            sandbox=self._settings.codex_sandbox,
            model=self._settings.codex_model,
            reasoning_effort=self._settings.codex_reasoning_effort,
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=working_dir,
                env=self._codex_env(working_dir),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            duration = time.monotonic() - started
            return CodexResult(
                command=command,
                repo_path=str(working_dir),
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            return CodexResult(
                command=command,
                repo_path=str(working_dir),
                stdout=_decode_timeout_output(exc.stdout),
                stderr=_decode_timeout_output(exc.stderr) or f"Codex command timed out after {timeout_seconds}s.",
                exit_code=-1,
                duration_seconds=duration,
                timed_out=True,
            )


def _with_api_key(env: dict[str, str] | None, api_key: str) -> dict[str, str]:
    merged = dict(env if env is not None else os.environ)
    merged["CODEX_API_KEY"] = api_key
    return merged


def run_codex_task(
    repo_path: str,
    task_prompt: str,
    timeout_seconds: int = 1800,
) -> CodexResult:
    return CodexService().run_codex_task(
        repo_path=repo_path,
        task_prompt=task_prompt,
        timeout_seconds=timeout_seconds,
    )


def _codex_command(
    codex_command: str,
    task_prompt: str,
    *,
    sandbox: str = "",
    model: str = "",
    reasoning_effort: str = "",
) -> list[str]:
    command_parts = shlex.split(codex_command, posix=os.name != "nt")
    if not command_parts:
        raise ValueError("CODEX_COMMAND must not be empty.")
    if "exec" not in command_parts:
        command_parts.append("exec")
    if sandbox and not {"-s", "--sandbox", "--full-auto"} & set(command_parts):
        command_parts += ["--sandbox", sandbox]
    if model and not {"-m", "--model"} & set(command_parts):
        command_parts += ["--model", model]
    if reasoning_effort:
        command_parts += ["-c", f"model_reasoning_effort={reasoning_effort}"]
    return [*command_parts, task_prompt]


def _decode_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
