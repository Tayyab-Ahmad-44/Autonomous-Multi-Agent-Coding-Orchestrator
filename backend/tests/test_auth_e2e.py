from __future__ import annotations

import os
from unittest import TestCase

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import database as database_module
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app


class AuthEndToEndTests(TestCase):
    """Exercises the real signup -> login -> bearer-token flow with no
    dependency_overrides for get_current_user, unlike every other test file's
    shortcut, to prove hashing, JWT issuance/verification, HTTPBearer parsing,
    and mission/repo ownership actually wire together end to end."""

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
        self.client = TestClient(app)

        self._original_secret = os.environ.get("JWT_SECRET_KEY")
        os.environ["JWT_SECRET_KEY"] = "e2e-test-secret-key-at-least-32-bytes"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        database_module._engine = self.original_engine
        database_module._session_local = self.original_session_local
        if self._original_secret is None:
            os.environ.pop("JWT_SECRET_KEY", None)
        else:
            os.environ["JWT_SECRET_KEY"] = self._original_secret
        get_settings.cache_clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _signup_and_login(self, email: str, password: str = "correct-horse-battery") -> dict:
        signup = self.client.post("/auth/signup", json={"email": email, "password": password})
        self.assertEqual(signup.status_code, 201)

        login = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_signup_login_create_repo_and_mission_end_to_end(self) -> None:
        headers = self._signup_and_login("alice@example.com")

        me = self.client.get("/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        user_id = me.json()["id"]

        repo_response = self.client.post(
            "/repos",
            json={"repo_url": "https://github.com/octocat/hello-world", "default_branch": "main"},
            headers=headers,
        )
        self.assertEqual(repo_response.status_code, 201)
        repo_id = repo_response.json()["id"]
        self.assertEqual(repo_response.json()["user_id"], user_id)

        mission_response = self.client.post(
            "/missions",
            json={"repo_id": repo_id, "title": "Build login system", "goal": "Build auth"},
            headers=headers,
        )
        self.assertEqual(mission_response.status_code, 201)
        mission_body = mission_response.json()
        self.assertEqual(mission_body["owner_id"], user_id)
        self.assertEqual(mission_body["repo_id"], repo_id)

        fetched = self.client.get(f"/missions/{mission_body['id']}", headers=headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["id"], mission_body["id"])

    def test_second_user_cannot_see_first_users_mission(self) -> None:
        alice_headers = self._signup_and_login("alice@example.com")
        repo_response = self.client.post(
            "/repos",
            json={"repo_url": "https://github.com/octocat/hello-world", "default_branch": "main"},
            headers=alice_headers,
        )
        mission_response = self.client.post(
            "/missions",
            json={
                "repo_id": repo_response.json()["id"],
                "title": "Build login system",
                "goal": "Build auth",
            },
            headers=alice_headers,
        )
        mission_id = mission_response.json()["id"]

        bob_headers = self._signup_and_login("bob@example.com")

        response = self.client.get(f"/missions/{mission_id}", headers=bob_headers)

        self.assertEqual(response.status_code, 404)

    def test_mission_creation_without_token_is_rejected(self) -> None:
        response = self.client.post(
            "/missions",
            json={"repo_id": "00000000-0000-0000-0000-000000000000", "title": "x", "goal": "y"},
        )

        self.assertEqual(response.status_code, 401)
