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
from app.models import MemorySource, MemoryStatus, User


class PreferenceEndpointTests(TestCase):
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

    def test_stating_a_preference_records_it_as_user_stated(self) -> None:
        response = self.client.post(
            "/preferences", json={"key": "test_framework", "value": "pytest, never unittest"}
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["key"], "test_framework")
        self.assertEqual(body["source"], MemorySource.user_stated.value)
        self.assertEqual(body["status"], MemoryStatus.active.value)

    def test_restating_a_key_supersedes_the_previous_value(self) -> None:
        self.client.post("/preferences", json={"key": "test_framework", "value": "unittest"})
        self.client.post("/preferences", json={"key": "test_framework", "value": "pytest"})

        listed = self.client.get("/preferences").json()

        self.assertEqual([(p["key"], p["value"]) for p in listed], [("test_framework", "pytest")])

    def test_deleting_a_preference_retires_it(self) -> None:
        created = self.client.post(
            "/preferences", json={"key": "test_framework", "value": "pytest"}
        ).json()

        response = self.client.delete(f"/preferences/{created['id']}")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/preferences").json(), [])

    def test_preferences_are_not_visible_to_another_user(self) -> None:
        created = self.client.post(
            "/preferences", json={"key": "test_framework", "value": "pytest"}
        ).json()

        app.dependency_overrides[get_current_user] = lambda: self.user_b

        self.assertEqual(self.client.get("/preferences").json(), [])
        self.assertEqual(self.client.delete(f"/preferences/{created['id']}").status_code, 404)
