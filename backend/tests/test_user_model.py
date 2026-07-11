from __future__ import annotations

from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import User


class UserModelTests(TestCase):
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

    def test_creates_user_with_defaults(self) -> None:
        db = self.session_local()
        try:
            user = User(email="alice@example.com", hashed_password="hashed")
            db.add(user)
            db.commit()
            db.refresh(user)

            self.assertIsNotNone(user.id)
            self.assertEqual(user.email, "alice@example.com")
            self.assertIsNotNone(user.created_at)
            self.assertIsNotNone(user.updated_at)
        finally:
            db.close()

    def test_duplicate_email_raises_integrity_error(self) -> None:
        db = self.session_local()
        try:
            db.add(User(email="bob@example.com", hashed_password="hashed-1"))
            db.commit()

            db.add(User(email="bob@example.com", hashed_password="hashed-2"))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()
