from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitServiceError(RuntimeError):
    pass


GENERATED_FILE_PATTERNS = (
    "*.log",
    "logs/",
    "__pycache__/",
    ".pytest_cache/",
    ".venv/",
    "node_modules/",
    "test-results/",
    "playwright-report/",
)


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

    def clone_repo(self, repo_url: str, destination_path: str) -> GitResult:
        dest = Path(destination_path).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        return self._run_git(str(dest), ["clone", repo_url, "."])

    def fetch(self, path: str) -> GitResult:
        return self._run_git(path, ["fetch", "--all", "--prune"])

    def checkout(self, path: str, branch: str) -> str:
        result = self._run_git(path, ["checkout", branch])
        return result.stdout.strip() or result.stderr.strip()

    def pull(self, path: str) -> str:
        result = self._run_git(path, ["pull"])
        return result.stdout.strip()

    def create_or_checkout_branch(self, path: str, branch: str) -> str:
        result = self._run_git(path, ["checkout", branch], check=False)
        if result.exit_code == 0:
            return result.stdout.strip() or result.stderr.strip()
        result = self._run_git(path, ["checkout", "-b", branch])
        return result.stdout.strip() or result.stderr.strip()

    def ensure_local_excludes(self, path: str, patterns: tuple[str, ...] = GENERATED_FILE_PATTERNS) -> None:
        """Keep generated files (logs, caches) out of worker commits without
        touching the repo's own .gitignore, via .git/info/exclude."""
        result = self._run_git(path, ["rev-parse", "--git-path", "info/exclude"], check=False)
        if result.exit_code != 0 or not result.stdout.strip():
            return
        exclude = Path(path) / result.stdout.strip()
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        missing = [p for p in patterns if p not in existing.splitlines()]
        if missing:
            header = "" if "# agent-orchestrator" in existing else "\n# agent-orchestrator: generated files\n"
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(header + "\n".join(missing) + "\n")

    def branch_exists(self, path: str, branch: str) -> bool:
        result = self._run_git(path, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        return result.exit_code == 0

    def merge_branch(self, path: str, branch: str) -> str:
        """Merge `branch` into the currently checked-out branch."""
        result = self._run_git(path, ["merge", "--no-edit", branch])
        return result.stdout.strip() or result.stderr.strip()

    def commits_ahead(self, path: str, base: str, head: str) -> int:
        """Number of commits on `head` that are not on `base`."""
        result = self._run_git(path, ["rev-list", "--count", f"{base}..{head}"])
        return int(result.stdout.strip() or 0)

    def get_remote_url(self, path: str) -> str:
        result = self._run_git(path, ["remote", "get-url", "origin"])
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
