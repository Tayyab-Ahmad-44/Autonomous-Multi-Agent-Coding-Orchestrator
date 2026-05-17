from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.services.git_service import GitService, GitServiceError


class GitServiceTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.service = GitService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_is_git_repo_returns_true_for_git_worktree(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="true\n",
                stderr="",
            ),
        ) as run:
            result = self.service.is_git_repo(str(self.repo_path))

        self.assertTrue(result)
        self.assertEqual(run.call_args.args[0], ["git", "rev-parse", "--is-inside-work-tree"])

    def test_branch_and_status_methods_return_stdout(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="main\n",
                stderr="",
            ),
        ):
            self.assertEqual(self.service.current_branch(str(self.repo_path)), "main")

    def test_commit_all_adds_and_commits(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, cwd, capture_output, text):
            calls.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="committed",
                stderr="",
            )

        with patch("app.services.git_service.subprocess.run", side_effect=fake_run):
            output = self.service.commit_all(str(self.repo_path), "Task: test")

        self.assertEqual(output, "committed")
        self.assertEqual(
            calls,
            [
                ["git", "add", "-A"],
                ["git", "commit", "-m", "Task: test"],
            ],
        )

    def test_git_error_is_raised_for_failed_checked_command(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="boom",
            ),
        ):
            with self.assertRaisesRegex(GitServiceError, "Git command failed"):
                self.service.current_branch(str(self.repo_path))
