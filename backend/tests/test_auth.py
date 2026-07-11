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


class AuthEndpointTests(TestCase):
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
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"
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

    def test_signup_creates_user(self) -> None:
        response = self.client.post(
            "/auth/signup",
            json={"email": "Alice@Example.com", "password": "correct-horse-battery"},
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "alice@example.com")
        self.assertIn("id", body)
        self.assertNotIn("password", body)
        self.assertNotIn("hashed_password", body)

    def test_signup_duplicate_email_returns_409(self) -> None:
        self.client.post(
            "/auth/signup",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )

        response = self.client.post(
            "/auth/signup",
            json={"email": "alice@example.com", "password": "another-password"},
        )

        self.assertEqual(response.status_code, 409)

    def test_login_returns_access_token(self) -> None:
        self.client.post(
            "/auth/signup",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )

        response = self.client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["access_token"])
        self.assertEqual(body["token_type"], "bearer")

    def test_login_wrong_password_returns_401(self) -> None:
        self.client.post(
            "/auth/signup",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )

        response = self.client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)

    def test_login_unknown_email_returns_401(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "whatever"},
        )

        self.assertEqual(response.status_code, 401)

    def test_me_with_valid_token_returns_current_user(self) -> None:
        self.client.post(
            "/auth/signup",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )
        login_response = self.client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "correct-horse-battery"},
        )
        token = login_response.json()["access_token"]

        response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "alice@example.com")

    def test_me_without_token_returns_401(self) -> None:
        response = self.client.get("/auth/me")

        self.assertEqual(response.status_code, 401)

    def test_me_with_invalid_token_returns_401(self) -> None:
        response = self.client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

        self.assertEqual(response.status_code, 401)
