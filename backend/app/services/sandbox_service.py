from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class SandboxResult:
    command: str
    repo_path: str
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    timed_out: bool = False


class BaseSandboxProvider(ABC):
    provider_name = "base"

    @abstractmethod
    def run_command(
        self,
        repo_path: str,
        command: str,
        timeout_seconds: int = 300,
    ) -> SandboxResult:
        raise NotImplementedError

    def run_test_commands(
        self,
        repo_path: str,
        commands: list[str],
        timeout_seconds: int = 300,
    ) -> list[SandboxResult]:
        return [
            self.run_command(
                repo_path=repo_path,
                command=command,
                timeout_seconds=timeout_seconds,
            )
            for command in commands
        ]


class LocalSandboxProvider(BaseSandboxProvider):
    provider_name = "local"

    def run_command(
        self,
        repo_path: str,
        command: str,
        timeout_seconds: int = 300,
    ) -> SandboxResult:
        normalized_command = command.strip()
        if not normalized_command:
            raise ValueError("Sandbox command must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        working_dir = Path(repo_path).expanduser().resolve()
        if not working_dir.exists() or not working_dir.is_dir():
            raise ValueError(f"repo_path must be an existing directory: {repo_path}")

        started = time.monotonic()
        try:
            completed = subprocess.run(
                normalized_command,
                cwd=working_dir,
                capture_output=True,
                shell=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration = time.monotonic() - started
            return SandboxResult(
                command=normalized_command,
                repo_path=str(working_dir),
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            return SandboxResult(
                command=normalized_command,
                repo_path=str(working_dir),
                stdout=_decode_timeout_output(exc.stdout),
                stderr=_decode_timeout_output(exc.stderr) or f"Command timed out after {timeout_seconds}s.",
                exit_code=-1,
                duration_seconds=duration,
                timed_out=True,
            )


class E2BSandboxProvider(BaseSandboxProvider):
    provider_name = "e2b"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or ""

    def run_command(
        self,
        repo_path: str,
        command: str,
        timeout_seconds: int = 300,
    ) -> SandboxResult:
        normalized_command = command.strip()
        if not normalized_command:
            raise ValueError("Sandbox command must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        if not self._api_key:
            raise RuntimeError("E2B sandbox provider selected but E2B_API_KEY is not configured.")

        raise NotImplementedError("E2B sandbox execution is not implemented yet.")


class SandboxService:
    def __init__(
        self,
        provider: BaseSandboxProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or _provider_from_settings(self._settings)

    @property
    def provider(self) -> BaseSandboxProvider:
        return self._provider

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    def run_command(
        self,
        repo_path: str,
        command: str,
        timeout_seconds: int = 300,
    ) -> SandboxResult:
        return self._provider.run_command(
            repo_path=repo_path,
            command=command,
            timeout_seconds=timeout_seconds,
        )

    def run_test_commands(
        self,
        repo_path: str,
        commands: list[str],
        timeout_seconds: int = 300,
    ) -> list[SandboxResult]:
        return self._provider.run_test_commands(
            repo_path=repo_path,
            commands=commands,
            timeout_seconds=timeout_seconds,
        )


def _provider_from_settings(settings: Settings) -> BaseSandboxProvider:
    if settings.sandbox_provider == "local":
        return LocalSandboxProvider()
    if settings.sandbox_provider == "e2b":
        return E2BSandboxProvider(api_key=settings.e2b_api_key)

    raise ValueError(f"Unsupported sandbox provider: {settings.sandbox_provider}")


def _decode_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
