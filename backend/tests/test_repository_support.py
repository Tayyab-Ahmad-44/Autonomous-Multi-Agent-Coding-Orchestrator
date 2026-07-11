from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from tests.factories import override_current_user, persist_test_repo, persist_test_user


class RepositorySupportEndpointTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        self.user = persist_test_user(self.session_local)
        self.repo = persist_test_repo(self.session_local, user_id=self.user.id)
        override_current_user(app, self.user)

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_mission_can_have_repository_config(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        created = self.client.post(
            f"/missions/{mission['id']}/repository",
            json={
                "provider": "local",
                "repo_url": "https://github.com/user/repo",
                "default_branch": "main",
                "local_path": "/workspace/repo",
            },
        )

        self.assertEqual(created.status_code, 201)
        created_body = created.json()
        self.assertEqual(created_body["mission_id"], mission["id"])
        self.assertEqual(created_body["provider"], "local")
        self.assertEqual(created_body["local_path"], "/workspace/repo")

        fetched = self.client.get(f"/missions/{mission['id']}/repository")

        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["id"], created_body["id"])

    def test_local_repository_requires_local_path(self) -> None:
        mission = self.client.post(
            "/missions",
            json={
                "repo_id": str(self.repo.id),
                "title": "Build login system",
                "goal": "Build email/password auth in this repo",
            },
        ).json()

        response = self.client.post(
            f"/missions/{mission['id']}/repository",
            json={
                "provider": "local",
                "repo_url": "https://github.com/user/repo",
                "default_branch": "main",
            },
        )

        self.assertEqual(response.status_code, 422)
