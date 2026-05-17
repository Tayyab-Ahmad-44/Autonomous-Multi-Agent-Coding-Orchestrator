from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class GitResult:
    command: list[str]
    repo_path: str
    stdout: str
    stderr: str
    exit_code: int


class GitService:
    def is_git_repo(self, path: str) -> bool:
        result = self._run_git(path, ["rev-parse", "--is-inside-work-tree"], check=False)
        return result.exit_code == 0 and result.stdout.strip() == "true"

    def current_branch(self, path: str) -> str:
        result = self._run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout.strip()

    def create_branch(self, path: str, branch_name: str) -> str:
        result = self._run_git(path, ["checkout", "-b", branch_name])
        return result.stdout.strip() or result.stderr.strip()

    def checkout_branch(self, path: str, branch_name: str) -> str:
        result = self._run_git(path, ["checkout", branch_name])
        return result.stdout.strip() or result.stderr.strip()

    def status(self, path: str) -> str:
        result = self._run_git(path, ["status", "--short"])
        return result.stdout

    def diff(self, path: str) -> str:
        result = self._run_git(path, ["diff"])
        return result.stdout

    def commit_all(self, path: str, message: str) -> str:
        if not message.strip():
            raise ValueError("Commit message must not be empty.")
        self._run_git(path, ["add", "-A"])
        result = self._run_git(path, ["commit", "-m", message])
        return result.stdout.strip() or result.stderr.strip()

    def get_latest_commit(self, path: str) -> str:
        result = self._run_git(path, ["rev-parse", "HEAD"])
        return result.stdout.strip()

    def _run_git(
        self,
        path: str,
        args: list[str],
        *,
        check: bool = True,
    ) -> GitResult:
        working_dir = Path(path).expanduser().resolve()
        if not working_dir.exists() or not working_dir.is_dir():
            raise ValueError(f"path must be an existing directory: {path}")

        command = ["git", *args]
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
        )
        result = GitResult(
            command=command,
            repo_path=str(working_dir),
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
        if check and result.exit_code != 0:
            raise GitServiceError(
                f"Git command failed with exit code {result.exit_code}: {' '.join(command)}\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result
