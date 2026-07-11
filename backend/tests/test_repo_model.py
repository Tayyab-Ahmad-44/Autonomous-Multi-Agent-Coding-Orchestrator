from __future__ import annotations

from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Repo, RepositoryProvider, User


class RepoModelTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_user(self, db, email: str = "alice@example.com") -> User:
        user = User(email=email, hashed_password="hashed")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def test_creates_repo_with_defaults(self) -> None:
        db = self.session_local()
        try:
            user = self._create_user(db)
            repo = Repo(
                user_id=user.id,
                provider=RepositoryProvider.github,
                repo_url="https://github.com/octocat/hello-world",
                default_branch="main",
                github_owner="octocat",
                github_repo="hello-world",
            )
            db.add(repo)
            db.commit()
            db.refresh(repo)

            self.assertIsNotNone(repo.id)
            self.assertEqual(repo.user_id, user.id)
            self.assertEqual(repo.default_branch, "main")
            self.assertIsNotNone(repo.created_at)
            self.assertIsNotNone(repo.updated_at)
        finally:
            db.close()

    def test_same_user_cannot_save_same_repo_url_twice(self) -> None:
        db = self.session_local()
        try:
            user = self._create_user(db)
            db.add(
                Repo(
                    user_id=user.id,
                    provider=RepositoryProvider.github,
                    repo_url="https://github.com/octocat/hello-world",
                    default_branch="main",
                )
            )
            db.commit()

            db.add(
                Repo(
                    user_id=user.id,
                    provider=RepositoryProvider.github,
                    repo_url="https://github.com/octocat/hello-world",
                    default_branch="main",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_different_users_can_save_the_same_repo_url(self) -> None:
        db = self.session_local()
        try:
            user_a = self._create_user(db, email="alice@example.com")
            user_b = self._create_user(db, email="bob@example.com")

            db.add(
                Repo(
                    user_id=user_a.id,
                    provider=RepositoryProvider.github,
                    repo_url="https://github.com/octocat/hello-world",
                    default_branch="main",
                )
            )
            db.add(
                Repo(
                    user_id=user_b.id,
                    provider=RepositoryProvider.github,
                    repo_url="https://github.com/octocat/hello-world",
                    default_branch="main",
                )
            )
            db.commit()

            self.assertEqual(db.query(Repo).count(), 2)
        finally:
            db.close()
