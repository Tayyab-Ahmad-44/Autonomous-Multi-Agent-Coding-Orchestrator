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

    def _ok(self, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)

    def _fail(self, stderr: str = "error") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)

    # --- clone_repo ---

    def test_clone_repo_creates_destination_dir(self) -> None:
        dest = self.repo_path / "new_clone"
        with patch("app.services.git_service.subprocess.run", return_value=self._ok()) as mock_run:
            self.service.clone_repo("https://github.com/example/repo.git", str(dest))
        self.assertTrue(dest.exists())
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd, ["git", "clone", "https://github.com/example/repo.git", "."])

    def test_clone_repo_raises_on_failure(self) -> None:
        dest = self.repo_path / "new_clone"
        with patch("app.services.git_service.subprocess.run", return_value=self._fail("fatal: repo not found")):
            with self.assertRaises(GitServiceError):
                self.service.clone_repo("https://github.com/example/repo.git", str(dest))

    # --- fetch ---

    def test_fetch_calls_fetch_all_prune(self) -> None:
        with patch("app.services.git_service.subprocess.run", return_value=self._ok()) as mock_run:
            self.service.fetch(str(self.repo_path))
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd, ["git", "fetch", "--all", "--prune"])

    def test_fetch_raises_on_failure(self) -> None:
        with patch("app.services.git_service.subprocess.run", return_value=self._fail()):
            with self.assertRaises(GitServiceError):
                self.service.fetch(str(self.repo_path))

    # --- checkout ---

    def test_checkout_returns_output(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=self._ok(stderr="Switched to branch 'main'"),
        ):
            result = self.service.checkout(str(self.repo_path), "main")
        self.assertEqual(result, "Switched to branch 'main'")

    def test_checkout_raises_on_failure(self) -> None:
        with patch("app.services.git_service.subprocess.run", return_value=self._fail("branch not found")):
            with self.assertRaises(GitServiceError):
                self.service.checkout(str(self.repo_path), "nonexistent")

    # --- pull ---

    def test_pull_returns_stdout(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=self._ok(stdout="Already up to date."),
        ):
            result = self.service.pull(str(self.repo_path))
        self.assertEqual(result, "Already up to date.")

    def test_pull_raises_on_failure(self) -> None:
        with patch("app.services.git_service.subprocess.run", return_value=self._fail("fatal: no remote")):
            with self.assertRaises(GitServiceError):
                self.service.pull(str(self.repo_path))

    # --- create_or_checkout_branch ---

    def test_create_or_checkout_branch_checks_out_existing(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=self._ok(stderr="Switched to branch 'mission/abc'"),
        ) as mock_run:
            result = self.service.create_or_checkout_branch(str(self.repo_path), "mission/abc")
        self.assertEqual(result, "Switched to branch 'mission/abc'")
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(mock_run.call_args.args[0], ["git", "checkout", "mission/abc"])

    def test_create_or_checkout_branch_creates_when_missing(self) -> None:
        responses = [
            self._fail("pathspec not found"),
            self._ok(stderr="Switched to a new branch 'mission/abc'"),
        ]
        with patch("app.services.git_service.subprocess.run", side_effect=responses) as mock_run:
            result = self.service.create_or_checkout_branch(str(self.repo_path), "mission/abc")
        self.assertEqual(result, "Switched to a new branch 'mission/abc'")
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(mock_run.call_args_list[1].args[0], ["git", "checkout", "-b", "mission/abc"])

    # --- get_remote_url ---

    def test_get_remote_url_returns_stripped_url(self) -> None:
        with patch(
            "app.services.git_service.subprocess.run",
            return_value=self._ok(stdout="https://github.com/user/repo\n"),
        ):
            result = self.service.get_remote_url(str(self.repo_path))
        self.assertEqual(result, "https://github.com/user/repo")

    def test_get_remote_url_raises_on_failure(self) -> None:
        with patch("app.services.git_service.subprocess.run", return_value=self._fail("No such remote")):
            with self.assertRaises(GitServiceError):
                self.service.get_remote_url(str(self.repo_path))
