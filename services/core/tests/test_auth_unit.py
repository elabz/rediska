"""Unit tests for authentication functionality.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Password hashing and verification
- Session creation, validation, and expiry
- Admin bootstrap functionality
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session as DBSession

from tests.factories import create_local_user, create_provider


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password_returns_string(self):
        """Test that hashing a password returns a string."""
        from rediska_core.domain.services.auth import hash_password

        result = hash_password("my-secure-password")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_password_is_not_plaintext(self):
        """Test that the hash is different from the plaintext password."""
        from rediska_core.domain.services.auth import hash_password

        password = "my-secure-password"
        result = hash_password(password)

        assert result != password

    def test_hash_password_produces_different_hashes(self):
        """Test that hashing the same password twice produces different hashes (salted)."""
        from rediska_core.domain.services.auth import hash_password

        password = "my-secure-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Argon2 includes random salt, so hashes should differ
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test that correct password verification returns True."""
        from rediska_core.domain.services.auth import hash_password, verify_password

        password = "my-secure-password"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password verification returns False."""
        from rediska_core.domain.services.auth import hash_password, verify_password

        password = "my-secure-password"
        hashed = hash_password(password)

        assert verify_password("wrong-password", hashed) is False

    def test_verify_password_empty_password(self):
        """Test that empty password fails verification."""
        from rediska_core.domain.services.auth import hash_password, verify_password

        hashed = hash_password("my-secure-password")

        assert verify_password("", hashed) is False

    def test_hash_password_handles_unicode(self):
        """Test that unicode passwords are handled correctly."""
        from rediska_core.domain.services.auth import hash_password, verify_password

        password = "пароль-日本語-🔐"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True


class TestSessionService:
    """Tests for session creation and management."""

    def test_create_session_returns_session_id(self, db_session: DBSession):
        """Test that creating a session returns a valid session ID."""
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        session_id = auth_service.create_session(user.id, expire_hours=24)

        assert session_id is not None
        assert isinstance(session_id, str)
        # Should be a valid UUID
        UUID(session_id)

    def test_create_session_persists_to_db(self, db_session: DBSession):
        """Test that session is persisted to database."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        session_id = auth_service.create_session(user.id, expire_hours=24)
        db_session.flush()

        session = db_session.query(Session).filter_by(id=session_id).first()
        assert session is not None
        assert session.user_id == user.id

    def test_create_session_sets_expiry(self, db_session: DBSession):
        """Test that session expiry is set correctly."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)
        expire_hours = 24

        session_id = auth_service.create_session(user.id, expire_hours=expire_hours)
        db_session.flush()

        session = db_session.query(Session).filter_by(id=session_id).first()
        assert session is not None

        # Expiry should be approximately expire_hours from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
        # Allow 1 minute tolerance
        assert abs((session.expires_at.replace(tzinfo=timezone.utc) - expected_expiry).total_seconds()) < 60

    def test_validate_session_valid(self, db_session: DBSession):
        """Test that a valid session passes validation."""
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        session_id = auth_service.create_session(user.id, expire_hours=24)
        db_session.flush()

        validated_user = auth_service.validate_session(session_id)
        assert validated_user is not None
        assert validated_user.id == user.id

    def test_validate_session_expired(self, db_session: DBSession):
        """Test that an expired session fails validation."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        session_id = auth_service.create_session(user.id, expire_hours=24)
        db_session.flush()

        # Manually expire the session
        session = db_session.query(Session).filter_by(id=session_id).first()
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.flush()

        validated_user = auth_service.validate_session(session_id)
        assert validated_user is None

    def test_validate_session_nonexistent(self, db_session: DBSession):
        """Test that a nonexistent session fails validation."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        validated_user = auth_service.validate_session("nonexistent-session-id")
        assert validated_user is None

    def test_validate_session_invalid_format(self, db_session: DBSession):
        """Test that an invalid session ID format fails validation."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        validated_user = auth_service.validate_session("")
        assert validated_user is None

    def test_invalidate_session(self, db_session: DBSession):
        """Test that invalidating a session removes it."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        session_id = auth_service.create_session(user.id, expire_hours=24)
        db_session.flush()

        # Verify session exists
        assert db_session.query(Session).filter_by(id=session_id).first() is not None

        # Invalidate
        auth_service.invalidate_session(session_id)
        db_session.flush()

        # Verify session is removed
        assert db_session.query(Session).filter_by(id=session_id).first() is None

    def test_invalidate_session_nonexistent(self, db_session: DBSession):
        """Test that invalidating a nonexistent session doesn't raise."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        # Should not raise
        auth_service.invalidate_session("nonexistent-session-id")

    def test_invalidate_all_user_sessions(self, db_session: DBSession):
        """Test that all sessions for a user can be invalidated."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        # Create multiple sessions
        session_ids = [
            auth_service.create_session(user.id, expire_hours=24)
            for _ in range(3)
        ]
        db_session.flush()

        # Verify sessions exist
        assert db_session.query(Session).filter_by(user_id=user.id).count() == 3

        # Invalidate all
        auth_service.invalidate_all_user_sessions(user.id)
        db_session.flush()

        # Verify all sessions are removed
        assert db_session.query(Session).filter_by(user_id=user.id).count() == 0


class TestAuthenticateUser:
    """Tests for user authentication flow."""

    def test_authenticate_user_success(self, db_session: DBSession):
        """Test successful user authentication."""
        from rediska_core.domain.services.auth import AuthService, hash_password

        password = "correct-password"
        user = create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        auth_service = AuthService(db_session)

        authenticated_user = auth_service.authenticate_user("testuser", password)

        assert authenticated_user is not None
        assert authenticated_user.id == user.id

    def test_authenticate_user_wrong_password(self, db_session: DBSession):
        """Test authentication fails with wrong password."""
        from rediska_core.domain.services.auth import AuthService, hash_password

        user = create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password("correct-password"),
        )
        auth_service = AuthService(db_session)

        authenticated_user = auth_service.authenticate_user("testuser", "wrong-password")

        assert authenticated_user is None

    def test_authenticate_user_nonexistent(self, db_session: DBSession):
        """Test authentication fails for nonexistent user."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        authenticated_user = auth_service.authenticate_user("nonexistent", "password")

        assert authenticated_user is None

    def test_authenticate_updates_last_login(self, db_session: DBSession):
        """Test that successful auth updates last_login_at."""
        from rediska_core.domain.services.auth import AuthService, hash_password

        password = "correct-password"
        user = create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        original_last_login = user.last_login_at
        auth_service = AuthService(db_session)

        auth_service.authenticate_user("testuser", password)
        db_session.flush()
        db_session.refresh(user)

        assert user.last_login_at is not None
        if original_last_login is not None:
            assert user.last_login_at > original_last_login


class TestAdminBootstrap:
    """Tests for admin user bootstrap functionality."""

    def test_bootstrap_admin_creates_user(self, db_session: DBSession):
        """Test that bootstrap creates admin user when none exists."""
        from rediska_core.domain.models import LocalUser
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        # No users should exist initially
        assert db_session.query(LocalUser).count() == 0

        user = auth_service.bootstrap_admin("admin", "admin-password")
        db_session.flush()

        assert user is not None
        assert user.username == "admin"
        assert db_session.query(LocalUser).count() == 1

    def test_bootstrap_admin_password_is_hashed(self, db_session: DBSession):
        """Test that bootstrap creates user with hashed password."""
        from rediska_core.domain.services.auth import AuthService, verify_password

        auth_service = AuthService(db_session)

        password = "admin-password"
        user = auth_service.bootstrap_admin("admin", password)
        db_session.flush()

        # Password should be hashed, not plaintext
        assert user.password_hash != password
        assert verify_password(password, user.password_hash) is True

    def test_bootstrap_admin_returns_existing(self, db_session: DBSession):
        """Test that bootstrap returns existing user if one exists."""
        from rediska_core.domain.models import LocalUser
        from rediska_core.domain.services.auth import AuthService

        # Create existing user
        existing = create_local_user(db_session, username="existing")
        auth_service = AuthService(db_session)

        user = auth_service.bootstrap_admin("admin", "password")

        # Should return existing user, not create new one
        assert user.id == existing.id
        assert db_session.query(LocalUser).count() == 1

    def test_bootstrap_admin_validates_username(self, db_session: DBSession):
        """Test that bootstrap validates username format."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        with pytest.raises(ValueError, match="username"):
            auth_service.bootstrap_admin("", "password")

    def test_bootstrap_admin_validates_password(self, db_session: DBSession):
        """Test that bootstrap validates password requirements."""
        from rediska_core.domain.services.auth import AuthService

        auth_service = AuthService(db_session)

        with pytest.raises(ValueError, match="password"):
            auth_service.bootstrap_admin("admin", "")

        with pytest.raises(ValueError, match="password"):
            auth_service.bootstrap_admin("admin", "short")  # Too short


class TestCleanupExpiredSessions:
    """Tests for expired session cleanup."""

    def test_cleanup_removes_expired_sessions(self, db_session: DBSession):
        """Test that cleanup removes expired sessions."""
        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import AuthService

        user = create_local_user(db_session)
        auth_service = AuthService(db_session)

        # Create some sessions
        valid_session = auth_service.create_session(user.id, expire_hours=24)
        expired_session = auth_service.create_session(user.id, expire_hours=24)
        db_session.flush()

        # Manually expire one session
        session = db_session.query(Session).filter_by(id=expired_session).first()
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.flush()

        # Cleanup
        removed_count = auth_service.cleanup_expired_sessions()
        db_session.flush()

        assert removed_count == 1
        assert db_session.query(Session).filter_by(id=valid_session).first() is not None
        assert db_session.query(Session).filter_by(id=expired_session).first() is None
