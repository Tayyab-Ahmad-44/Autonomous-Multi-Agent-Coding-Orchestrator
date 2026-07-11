from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core import database as database_module
from app.core.database import Base, get_db
from app.main import app
from app.models import User


class RepoEndpointTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.original_engine = database_module._engine
        self.original_session_local = database_module._session_local
        database_module._engine = self.engine
        database_module._session_local = self.session_local

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        self.user_a = self._persist_user("alice@example.com")
        self.user_b = self._persist_user("bob@example.com")
        app.dependency_overrides[get_current_user] = lambda: self.user_a

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        database_module._engine = self.original_engine
        database_module._session_local = self.original_session_local
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _persist_user(self, email: str) -> User:
        db = self.session_local()
        try:
            user = User(email=email, hashed_password="hashed")
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user
        finally:
            db.close()

    def test_create_repo(self) -> None:
        response = self.client.post(
            "/repos",
            json={"repo_url": "https://github.com/octocat/hello-world", "default_branch": "main"},
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["repo_url"], "https://github.com/octocat/hello-world")
        self.assertEqual(body["provider"], "github")
        self.assertEqual(body["github_owner"], "octocat")
        self.assertEqual(body["github_repo"], "hello-world")
        self.assertEqual(body["user_id"], str(self.user_a.id))

    def test_create_duplicate_repo_returns_409(self) -> None:
        self.client.post("/repos", json={"repo_url": "https://github.com/octocat/hello-world"})

        response = self.client.post("/repos", json={"repo_url": "https://github.com/octocat/hello-world"})

        self.assertEqual(response.status_code, 409)

    def test_list_repos_returns_only_current_users_repos(self) -> None:
        self.client.post("/repos", json={"repo_url": "https://github.com/octocat/hello-world"})

        app.dependency_overrides[get_current_user] = lambda: self.user_b
        self.client.post("/repos", json={"repo_url": "https://github.com/octocat/other-repo"})

        app.dependency_overrides[get_current_user] = lambda: self.user_a
        response = self.client.get("/repos")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["repo_url"], "https://github.com/octocat/hello-world")

    def test_repos_require_authentication(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)

        response = self.client.get("/repos")

        self.assertEqual(response.status_code, 401)
