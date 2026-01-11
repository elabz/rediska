"""Pytest configuration and fixtures for worker tests.

These fixtures enable testing Celery tasks without requiring:
- Running Redis/Celery
- Database connections
- External provider APIs
"""

import os
import sys
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

# Add worker package to path
worker_path = Path(__file__).parent.parent
sys.path.insert(0, str(worker_path))

# Set test environment variables before importing celery_app
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
os.environ.setdefault("MYSQL_URL", "mysql+pymysql://test:test@localhost:3306/test")
os.environ.setdefault("BACKUPS_PATH", "/tmp/rediska_test_backups")
os.environ.setdefault("ATTACHMENTS_PATH", "/tmp/rediska_test_attachments")


@pytest.fixture(scope="session")
def celery_config() -> dict[str, Any]:
    """Celery configuration for testing."""
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True,
        "task_eager_propagates": True,
    }


@pytest.fixture(scope="session")
def celery_enable_logging() -> bool:
    """Enable Celery logging during tests."""
    return True


@pytest.fixture
def mock_celery_app():
    """Mock Celery app for unit testing tasks."""
    from rediska_worker.celery_app import app

    # Configure for eager execution (synchronous)
    app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
    return app


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    session.flush = MagicMock()
    return session


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = MagicMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = 1
    redis.incr.return_value = 1
    redis.decr.return_value = 0
    return redis


@pytest.fixture
def temp_backup_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary backup directory."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    with patch.dict(os.environ, {"BACKUPS_PATH": str(backup_dir)}):
        yield backup_dir


@pytest.fixture
def temp_attachments_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary attachments directory with sample files."""
    att_dir = tmp_path / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)

    # Create some sample attachment files
    for i in range(5):
        (att_dir / f"file_{i}.txt").write_text(f"Sample attachment {i}")

    with patch.dict(os.environ, {"ATTACHMENTS_PATH": str(att_dir)}):
        yield att_dir


@pytest.fixture
def mock_provider_adapter():
    """Create a mock provider adapter."""
    adapter = MagicMock()
    adapter.list_conversations.return_value = []
    adapter.list_messages.return_value = []
    adapter.send_message.return_value = MagicMock(
        success=True,
        external_message_id="mock_msg_123",
        error_message=None,
        is_ambiguous=False,
    )
    adapter.fetch_profile.return_value = MagicMock(
        username="mock_user",
        created_utc=1234567890,
        karma=100,
    )
    return adapter


@pytest.fixture
def mock_crypto_service():
    """Create a mock crypto service."""
    crypto = MagicMock()
    crypto.encrypt.side_effect = lambda x: f"encrypted:{x}"
    crypto.decrypt.side_effect = lambda x: x.replace("encrypted:", "")
    return crypto


@pytest.fixture
def mock_settings():
    """Create mock application settings."""
    settings = MagicMock()
    settings.encryption_key = "test_encryption_key_32bytes_long!"
    settings.provider_reddit_client_id = "test_client_id"
    settings.provider_reddit_client_secret = "test_client_secret"
    settings.mysql_url = "mysql+pymysql://test:test@localhost:3306/test"
    return settings


@pytest.fixture
def mock_task_request():
    """Create a mock Celery task request object."""
    request = MagicMock()
    request.id = "test-task-id-123"
    request.retries = 0
    return request


class MockConversation:
    """Mock Conversation model for testing."""

    def __init__(
        self,
        id: int = 1,
        identity_id: int = 1,
        counterpart_account_id: int = 2,
        provider_id: str = "reddit",
    ):
        self.id = id
        self.identity_id = identity_id
        self.counterpart_account_id = counterpart_account_id
        self.provider_id = provider_id


class MockExternalAccount:
    """Mock ExternalAccount model for testing."""

    def __init__(
        self,
        id: int = 1,
        external_username: str = "test_user",
        external_user_id: str = "ext_123",
        provider_id: str = "reddit",
        remote_status: str = "active",
    ):
        self.id = id
        self.external_username = external_username
        self.external_user_id = external_user_id
        self.provider_id = provider_id
        self.remote_status = remote_status


class MockMessage:
    """Mock Message model for testing."""

    def __init__(
        self,
        id: int = 1,
        conversation_id: int = 1,
        identity_id: int | None = 1,
        body_text: str = "Test message",
        direction: str = "outgoing",
        status: str = "pending",
    ):
        self.id = id
        self.conversation_id = conversation_id
        self.identity_id = identity_id
        self.body_text = body_text
        self.direction = direction
        self.status = status


@pytest.fixture
def mock_conversation():
    """Create a mock conversation."""
    return MockConversation()


@pytest.fixture
def mock_external_account():
    """Create a mock external account."""
    return MockExternalAccount()


@pytest.fixture
def mock_message():
    """Create a mock message."""
    return MockMessage()
