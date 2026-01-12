"""Authentication service for Rediska.

Provides password hashing, session management, and user authentication.
Uses Argon2 for password hashing (recommended by OWASP).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session as DBSession

from rediska_core.domain.models import LocalUser, Session

# Password hasher configuration (OWASP recommendations)
_password_hasher = PasswordHasher(
    time_cost=3,  # Number of iterations
    memory_cost=65536,  # 64MB memory
    parallelism=4,  # Number of parallel threads
    hash_len=32,  # Length of hash
    salt_len=16,  # Length of salt
)

# Minimum password length
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash a password using Argon2.

    Args:
        password: The plaintext password to hash.

    Returns:
        The hashed password string.
    """
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash.

    Args:
        password: The plaintext password to verify.
        password_hash: The hash to verify against.

    Returns:
        True if the password matches, False otherwise.
    """
    if not password:
        return False

    try:
        _password_hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        # Handle any other argon2 exceptions (invalid hash format, etc.)
        return False


class AuthService:
    """Service for authentication operations."""

    def __init__(self, db: DBSession):
        """Initialize the auth service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def create_session(
        self,
        user_id: int,
        expire_hours: int = 24 * 7,
        data: Optional[dict] = None,
    ) -> str:
        """Create a new session for a user.

        Args:
            user_id: The ID of the user to create a session for.
            expire_hours: Hours until the session expires (default: 1 week).
            data: Optional JSON data to store with the session.

        Returns:
            The session ID (UUID string).
        """
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expire_hours)

        session = Session(
            id=session_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            data_json=data,
        )

        self.db.add(session)
        return session_id

    def validate_session(self, session_id: str) -> Optional[LocalUser]:
        """Validate a session and return the associated user.

        Args:
            session_id: The session ID to validate.

        Returns:
            The LocalUser if session is valid, None otherwise.
        """
        if not session_id:
            return None

        session = self.db.query(Session).filter_by(id=session_id).first()

        if session is None:
            return None

        # Check if expired
        now = datetime.now(timezone.utc)
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            return None

        # Get the user
        user = self.db.query(LocalUser).filter_by(id=session.user_id).first()
        return user

    def invalidate_session(self, session_id: str) -> None:
        """Invalidate (delete) a session.

        Args:
            session_id: The session ID to invalidate.
        """
        self.db.query(Session).filter_by(id=session_id).delete()

    def invalidate_all_user_sessions(self, user_id: int) -> None:
        """Invalidate all sessions for a user.

        Args:
            user_id: The user ID whose sessions should be invalidated.
        """
        self.db.query(Session).filter_by(user_id=user_id).delete()

    def authenticate_user(
        self, username: str, password: str
    ) -> Optional[LocalUser]:
        """Authenticate a user by username and password.

        Args:
            username: The username to authenticate.
            password: The password to verify.

        Returns:
            The LocalUser if authentication succeeds, None otherwise.
        """
        user = self.db.query(LocalUser).filter_by(username=username).first()

        if user is None:
            return None

        if not verify_password(password, user.password_hash):
            return None

        # Update last login time
        user.last_login_at = datetime.now(timezone.utc)

        return user

    def bootstrap_admin(self, username: str, password: str) -> LocalUser:
        """Bootstrap the admin user.

        Creates an admin user if no users exist. If a user already exists,
        returns the existing user.

        Args:
            username: The admin username.
            password: The admin password.

        Returns:
            The admin LocalUser.

        Raises:
            ValueError: If username or password are invalid.
        """
        # Validate inputs
        if not username or len(username.strip()) == 0:
            raise ValueError("username must not be empty")

        if not password or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"password must be at least {MIN_PASSWORD_LENGTH} characters"
            )

        # Check if any user exists
        existing_user = self.db.query(LocalUser).first()
        if existing_user is not None:
            return existing_user

        # Create admin user
        user = LocalUser(
            username=username.strip(),
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc),
        )

        self.db.add(user)
        self.db.flush()

        return user

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions.

        Returns:
            The number of sessions removed.
        """
        now = datetime.now(timezone.utc)
        result = self.db.query(Session).filter(Session.expires_at < now).delete()
        return result
