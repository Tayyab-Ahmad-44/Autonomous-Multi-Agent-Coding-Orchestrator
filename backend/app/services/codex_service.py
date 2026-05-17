from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings


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

        command = _codex_command(self._settings.codex_command, normalized_prompt)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=working_dir,
                capture_output=True,
                text=True,
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


def _codex_command(codex_command: str, task_prompt: str) -> list[str]:
    command_parts = shlex.split(codex_command, posix=os.name != "nt")
    if not command_parts:
        raise ValueError("CODEX_COMMAND must not be empty.")
    if "exec" in command_parts:
        return [*command_parts, task_prompt]
    return [*command_parts, "exec", task_prompt]


def _decode_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
