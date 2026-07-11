from __future__ import annotations

import os
from unittest import TestCase

import jwt

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class SecurityTests(TestCase):
    def setUp(self) -> None:
        self._original_secret = os.environ.get("JWT_SECRET_KEY")
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        if self._original_secret is None:
            os.environ.pop("JWT_SECRET_KEY", None)
        else:
            os.environ["JWT_SECRET_KEY"] = self._original_secret
        get_settings.cache_clear()

    def test_hash_and_verify_password_roundtrip(self) -> None:
        hashed = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", hashed))

    def test_verify_rejects_wrong_password(self) -> None:
        hashed = hash_password("correct horse battery staple")

        self.assertFalse(verify_password("wrong password", hashed))

    def test_create_and_decode_access_token_roundtrip(self) -> None:
        token = create_access_token(subject="user-123")

        payload = decode_access_token(token)

        self.assertEqual(payload["sub"], "user-123")

    def test_decode_rejects_expired_token(self) -> None:
        token = create_access_token(subject="user-123", expires_minutes=-1)

        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_access_token(token)
