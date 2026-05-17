from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx


class GitHubServiceError(RuntimeError):
    pass


@dataclass
class ParsedGitHubUrl:
    owner: str
    repo: str


class GitHubService:
    _API_BASE = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def parse_github_url(self, repo_url: str) -> ParsedGitHubUrl:
        match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", repo_url)
        if not match:
            raise GitHubServiceError(f"Cannot parse GitHub owner/repo from URL: {repo_url!r}")
        return ParsedGitHubUrl(owner=match.group(1), repo=match.group(2))

    def push_branch(self, local_path: str, branch: str, owner: str, repo: str) -> None:
        working_dir = Path(local_path).expanduser().resolve()
        if not working_dir.is_dir():
            raise GitHubServiceError(f"local_path is not a directory: {local_path}")

        # Embed token in URL so no interactive prompt is needed.
        # GIT_TERMINAL_PROMPT=0 ensures git fails fast rather than hanging.
        authenticated_url = (
            f"https://x-access-token:{self._token}@github.com/{owner}/{repo}.git"
        )
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        completed = subprocess.run(
            ["git", "push", authenticated_url, f"{branch}:{branch}"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            # Exclude authenticated_url from the message to avoid leaking the token.
            raise GitHubServiceError(
                f"git push failed (exit {completed.returncode}): "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str = "",
    ) -> str:
        url = f"{self._API_BASE}/repos/{owner}/{repo}/pulls"
        response = httpx.post(
            url,
            json={"title": title, "head": head, "base": base, "body": body},
            headers=self._headers,
            timeout=30.0,
        )

        if response.status_code == 422:
            # A PR for this branch may already exist.
            errors = response.json().get("errors", [])
            if any("already exists" in str(e.get("message", "")) for e in errors):
                existing = self._find_open_pr(owner, repo, head, base)
                if existing:
                    return existing
            raise GitHubServiceError(
                f"GitHub rejected PR creation (422): {response.text[:500]}"
            )

        if not response.is_success:
            raise GitHubServiceError(
                f"GitHub API error ({response.status_code}): {response.text[:500]}"
            )

        return response.json()["html_url"]

    def _find_open_pr(self, owner: str, repo: str, head: str, base: str) -> str | None:
        url = f"{self._API_BASE}/repos/{owner}/{repo}/pulls"
        response = httpx.get(
            url,
            params={"state": "open", "head": f"{owner}:{head}", "base": base},
            headers=self._headers,
            timeout=30.0,
        )
        if response.is_success and response.json():
            return response.json()[0]["html_url"]
        return None
