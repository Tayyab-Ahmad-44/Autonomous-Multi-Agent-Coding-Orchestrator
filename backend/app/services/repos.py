from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repo, RepositoryProvider


class RepoAlreadyExistsError(ValueError):
    pass


def parse_repo_url(repo_url: str) -> tuple[RepositoryProvider, str | None, str | None]:
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", repo_url)
    if match:
        return RepositoryProvider.github, match.group(1), match.group(2)
    return RepositoryProvider.local, None, None


def create_repo(db: Session, *, user_id: UUID, repo_url: str, default_branch: str = "main") -> Repo:
    existing = db.scalar(
        select(Repo).where(Repo.user_id == user_id, Repo.repo_url == repo_url)
    )
    if existing is not None:
        raise RepoAlreadyExistsError(f"Repo already saved: {repo_url}")

    provider, github_owner, github_repo = parse_repo_url(repo_url)
    repo = Repo(
        user_id=user_id,
        provider=provider,
        repo_url=repo_url,
        default_branch=default_branch,
        github_owner=github_owner,
        github_repo=github_repo,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def list_repos(db: Session, *, user_id: UUID, offset: int = 0, limit: int = 100) -> list[Repo]:
    statement = (
        select(Repo)
        .where(Repo.user_id == user_id)
        .order_by(Repo.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def get_repo(db: Session, *, repo_id: UUID, user_id: UUID) -> Repo | None:
    return db.scalar(select(Repo).where(Repo.id == repo_id, Repo.user_id == user_id))
