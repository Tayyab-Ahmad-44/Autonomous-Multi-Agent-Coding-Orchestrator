from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_current_user
from app.models import Repo, RepositoryProvider, User


def persist_test_user(session_local: sessionmaker[Session], email: str = "test-user@example.com") -> User:
    db = session_local()
    try:
        user = User(email=email, hashed_password="hashed")
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def persist_test_repo(
    session_local: sessionmaker[Session],
    *,
    user_id,
    repo_url: str = "https://github.com/octocat/hello-world",
    default_branch: str = "main",
) -> Repo:
    db = session_local()
    try:
        repo = Repo(
            user_id=user_id,
            provider=RepositoryProvider.github,
            repo_url=repo_url,
            default_branch=default_branch,
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)
        db.expunge(repo)
        return repo
    finally:
        db.close()


def override_current_user(app: FastAPI, user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def create_repo_via_api(
    client: TestClient,
    *,
    repo_url: str = "https://github.com/octocat/hello-world",
    default_branch: str = "main",
) -> dict[str, Any]:
    response = client.post("/repos", json={"repo_url": repo_url, "default_branch": default_branch})
    response.raise_for_status()
    return response.json()
