from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from learningloop.config import Settings
from learningloop.db import Database


class AuthenticationError(ValueError):
    """Raised when credentials cannot be accepted."""


class AuthService:
    """Small application-owned session auth for a private laboratory instance."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self._hasher = PasswordHasher()

    def hash_password(self, password: str) -> str:
        if len(password) < 12:
            raise AuthenticationError("password must contain at least 12 characters")
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def authenticate(self, username: str, password: str) -> dict:
        user = self.db.get_user_by_username(username.strip())
        if not user or user.get("disabled") or not user.get("password_hash"):
            raise AuthenticationError("invalid username or password")
        if not self.verify_password(user["password_hash"], password):
            raise AuthenticationError("invalid username or password")
        return user

    def issue_session(self, user_id: str) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.auth_session_hours)
        self.db.create_auth_session(self._hash_token(token), user_id, expires_at=expires_at)
        return token, expires_at

    def user_from_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        user = self.db.get_auth_session(self._hash_token(token))
        if user:
            user["id"] = user["user_id"]
        return user

    def revoke(self, token: str | None) -> None:
        if token:
            self.db.delete_auth_session(self._hash_token(token))

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
