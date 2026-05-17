from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.services.github_service import GitHubService, GitHubServiceError


TOKEN = "ghp_test_token"


def _svc() -> GitHubService:
    return GitHubService(token=TOKEN)


def _ok_push() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail_push(stderr: str = "error") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class TestParseGitHubUrl(TestCase):
    def test_https_url(self) -> None:
        result = _svc().parse_github_url("https://github.com/myorg/myrepo")
        self.assertEqual(result.owner, "myorg")
        self.assertEqual(result.repo, "myrepo")

    def test_https_url_with_git_suffix(self) -> None:
        result = _svc().parse_github_url("https://github.com/myorg/myrepo.git")
        self.assertEqual(result.owner, "myorg")
        self.assertEqual(result.repo, "myrepo")

    def test_ssh_url(self) -> None:
        result = _svc().parse_github_url("git@github.com:myorg/myrepo.git")
        self.assertEqual(result.owner, "myorg")
        self.assertEqual(result.repo, "myrepo")

    def test_invalid_url_raises(self) -> None:
        with self.assertRaises(GitHubServiceError):
            _svc().parse_github_url("https://gitlab.com/user/repo")


class TestPushBranch(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.local_path = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_push_succeeds(self) -> None:
        with patch("subprocess.run", return_value=_ok_push()) as mock_run:
            _svc().push_branch(self.local_path, "mission/abc12345", "myorg", "myrepo")

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "git")
        self.assertEqual(cmd[1], "push")
        # The authenticated URL should contain the token
        self.assertIn(TOKEN, cmd[2])
        self.assertIn("myorg/myrepo.git", cmd[2])
        self.assertEqual(cmd[3], "mission/abc12345:mission/abc12345")

    def test_push_does_not_leak_token_in_error(self) -> None:
        with patch("subprocess.run", return_value=_fail_push("remote: Permission denied")):
            with self.assertRaises(GitHubServiceError) as ctx:
                _svc().push_branch(self.local_path, "mission/abc12345", "myorg", "myrepo")
        # Token must not appear in the exception message
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_push_raises_for_missing_path(self) -> None:
        with self.assertRaises(GitHubServiceError):
            _svc().push_branch("/nonexistent/path", "mission/abc", "org", "repo")

    def test_push_raises_on_git_failure(self) -> None:
        with patch("subprocess.run", return_value=_fail_push("fatal: auth failed")):
            with self.assertRaises(GitHubServiceError):
                _svc().push_branch(self.local_path, "mission/abc", "org", "repo")


class TestCreatePullRequest(TestCase):
    def _mock_response(self, status_code: int, json_data: dict) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.text = str(json_data)
        resp.is_success = status_code < 400
        resp.raise_for_status = MagicMock()
        return resp

    def test_returns_pr_url_on_success(self) -> None:
        resp = self._mock_response(201, {"html_url": "https://github.com/org/repo/pull/1"})
        with patch("httpx.post", return_value=resp):
            url = _svc().create_pull_request("org", "repo", "mission/abc", "main", "My PR")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")

    def test_returns_existing_pr_url_on_422(self) -> None:
        fail_resp = self._mock_response(
            422,
            {"errors": [{"message": "A pull request already exists for org:mission/abc."}]},
        )
        existing_resp = self._mock_response(
            200,
            [{"html_url": "https://github.com/org/repo/pull/7"}],
        )
        with patch("httpx.post", return_value=fail_resp), \
             patch("httpx.get", return_value=existing_resp):
            url = _svc().create_pull_request("org", "repo", "mission/abc", "main", "My PR")

        self.assertEqual(url, "https://github.com/org/repo/pull/7")

    def test_raises_on_422_without_existing_pr(self) -> None:
        fail_resp = self._mock_response(422, {"errors": [{"message": "Validation failed"}]})
        no_pr_resp = self._mock_response(200, [])
        with patch("httpx.post", return_value=fail_resp), \
             patch("httpx.get", return_value=no_pr_resp):
            with self.assertRaises(GitHubServiceError):
                _svc().create_pull_request("org", "repo", "mission/abc", "main", "My PR")

    def test_raises_on_api_error(self) -> None:
        resp = self._mock_response(403, {"message": "Forbidden"})
        with patch("httpx.post", return_value=resp):
            with self.assertRaises(GitHubServiceError):
                _svc().create_pull_request("org", "repo", "mission/abc", "main", "My PR")
