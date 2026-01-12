"""Pytest configuration and fixtures for Rediska Core tests.

This module provides fixtures for:
- Database: SQLite in-memory for unit tests, test MySQL DB for integration
- HTTP client: AsyncClient for FastAPI testing
- Mocks: Redis, Elasticsearch, and external service mocks
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from rediska_core.config import Settings
from rediska_core.domain.models import Base


# -----------------------------------------------------------------------------
# Event Loop Fixture
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# -----------------------------------------------------------------------------
# Test Settings
# -----------------------------------------------------------------------------


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with safe defaults."""
    from rediska_core.infrastructure.crypto import CryptoService

    return Settings(
        mysql_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",  # Use DB 15 for tests
        elastic_url="http://localhost:9200",
        attachments_path="/tmp/rediska_test/attachments",
        backups_path="/tmp/rediska_test/backups",
        secret_key="test-secret-key-do-not-use-in-production",
        encryption_key=CryptoService.generate_key(),
        session_expire_hours=1,
        provider_reddit_enabled=True,
        provider_reddit_client_id="test_client_id",
        provider_reddit_client_secret="test_client_secret",
        provider_reddit_redirect_uri="https://rediska.local/providers/reddit/oauth/callback",
    )


# -----------------------------------------------------------------------------
# Synchronous Database Fixtures (for unit tests)
# -----------------------------------------------------------------------------


@pytest.fixture
def sync_engine():
    """Create a synchronous SQLite in-memory engine for testing."""
    from sqlalchemy import BigInteger, Integer

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable foreign key support for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Convert BigInteger to Integer for SQLite (required for autoincrement)
    # This is needed because SQLite only supports autoincrement on INTEGER PRIMARY KEY
    @event.listens_for(Base.metadata, "column_reflect")
    def receive_column_reflect(inspector, table, column_info):
        if isinstance(column_info.get("type"), BigInteger):
            column_info["type"] = Integer()

    # Also need to handle during table creation
    # Temporarily override BigInteger to compile as INTEGER for SQLite
    from sqlalchemy.dialects import sqlite
    original_visit = sqlite.dialect.type_compiler_cls.visit_BIGINT
    sqlite.dialect.type_compiler_cls.visit_BIGINT = lambda self, type_, **kw: "INTEGER"

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Restore original behavior
    sqlite.dialect.type_compiler_cls.visit_BIGINT = original_visit

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def sync_session_factory(sync_engine) -> sessionmaker[Session]:
    """Create a synchronous session factory."""
    return sessionmaker(
        bind=sync_engine,
        autocommit=False,
        autoflush=False,
    )


@pytest.fixture
def db_session(sync_session_factory) -> Generator[Session, None, None]:
    """Create a synchronous database session for testing."""
    session = sync_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# -----------------------------------------------------------------------------
# Asynchronous Database Fixtures (for integration tests)
# -----------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    """Create an async SQLite in-memory engine for testing."""
    from sqlalchemy.dialects import sqlite

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Temporarily override BigInteger to compile as INTEGER for SQLite
    # This is needed because SQLite only supports autoincrement on INTEGER PRIMARY KEY
    original_visit = sqlite.dialect.type_compiler_cls.visit_BIGINT
    sqlite.dialect.type_compiler_cls.visit_BIGINT = lambda self, type_, **kw: "INTEGER"

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Restore original behavior
    sqlite.dialect.type_compiler_cls.visit_BIGINT = original_visit

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session_factory(async_engine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory."""
    return async_sessionmaker(
        bind=async_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture
async def async_db_session(
    async_session_factory,
) -> AsyncGenerator[AsyncSession, None]:
    """Create an async database session for testing."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# -----------------------------------------------------------------------------
# FastAPI Test Client Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def test_app(test_settings, sync_engine, sync_session_factory) -> FastAPI:
    """Create a FastAPI test application with test settings and DB override."""
    from rediska_core.api.deps import get_db
    from rediska_core.main import app

    # Override settings
    app.state.settings = test_settings

    # Override the database dependency to use test database
    def override_get_db():
        session = sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    yield app

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture
async def client(test_app, db_session) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing FastAPI endpoints.

    Note: The db_session fixture is included to ensure the test database
    is set up before the client is created.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def authenticated_client(
    test_app, db_session, test_settings
) -> AsyncGenerator[AsyncClient, None]:
    """Create an authenticated HTTP client for testing protected endpoints.

    This fixture should be extended once authentication is implemented
    to include proper session/token setup.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        cookies={"session": "test-session-token"},  # Placeholder
    ) as ac:
        yield ac


# -----------------------------------------------------------------------------
# Mock Fixtures for External Services
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    """Mock Redis client for testing."""
    with patch("redis.Redis") as mock:
        mock_instance = MagicMock()
        mock.return_value = mock_instance

        # Setup common Redis operations
        mock_instance.get.return_value = None
        mock_instance.set.return_value = True
        mock_instance.delete.return_value = 1
        mock_instance.exists.return_value = 0
        mock_instance.expire.return_value = True
        mock_instance.incr.return_value = 1
        mock_instance.pipeline.return_value = MagicMock()

        yield mock_instance


@pytest.fixture
def mock_async_redis() -> Generator[AsyncMock, None, None]:
    """Mock async Redis client for testing."""
    with patch("redis.asyncio.Redis") as mock:
        mock_instance = AsyncMock()
        mock.return_value = mock_instance

        # Setup common async Redis operations
        mock_instance.get.return_value = None
        mock_instance.set.return_value = True
        mock_instance.delete.return_value = 1
        mock_instance.exists.return_value = 0
        mock_instance.expire.return_value = True
        mock_instance.incr.return_value = 1

        yield mock_instance


@pytest.fixture
def mock_elasticsearch() -> Generator[MagicMock, None, None]:
    """Mock Elasticsearch client for testing."""
    with patch("elasticsearch.Elasticsearch") as mock:
        mock_instance = MagicMock()
        mock.return_value = mock_instance

        # Setup common ES operations
        mock_instance.ping.return_value = True
        mock_instance.index.return_value = {"result": "created", "_id": "test-id"}
        mock_instance.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        mock_instance.delete.return_value = {"result": "deleted"}
        mock_instance.update.return_value = {"result": "updated"}
        mock_instance.indices.exists.return_value = True
        mock_instance.indices.create.return_value = {"acknowledged": True}

        yield mock_instance


@pytest.fixture
def mock_httpx_client() -> Generator[AsyncMock, None, None]:
    """Mock httpx.AsyncClient for testing external HTTP calls."""
    with patch("httpx.AsyncClient") as mock:
        mock_instance = AsyncMock()
        mock.return_value.__aenter__.return_value = mock_instance
        mock.return_value.__aexit__.return_value = None

        # Default response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.text = ""
        mock_instance.get.return_value = mock_response
        mock_instance.post.return_value = mock_response

        yield mock_instance


# -----------------------------------------------------------------------------
# Test Data Helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_provider_data() -> dict[str, Any]:
    """Sample provider data for testing."""
    return {
        "provider_id": "reddit",
        "display_name": "Reddit",
        "enabled": True,
    }


@pytest.fixture
def sample_identity_data() -> dict[str, Any]:
    """Sample identity data for testing."""
    return {
        "provider_id": "reddit",
        "external_username": "test_user",
        "external_user_id": "t2_abc123",
        "display_name": "Test User",
        "voice_config_json": {
            "system_prompt": "You are a helpful assistant.",
            "tone": "friendly",
            "style": "casual",
        },
        "is_default": True,
        "is_active": True,
    }


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample local user data for testing."""
    return {
        "username": "admin",
        "password": "test-password-123",
    }


@pytest.fixture
def sample_conversation_data(sample_identity_data) -> dict[str, Any]:
    """Sample conversation data for testing."""
    return {
        "provider_id": "reddit",
        "identity_id": 1,  # Will be set by actual identity
        "external_conversation_id": "conv_abc123",
        "counterpart_account_id": 1,  # Will be set by actual account
    }


@pytest.fixture
def sample_message_data() -> dict[str, Any]:
    """Sample message data for testing."""
    return {
        "provider_id": "reddit",
        "external_message_id": "msg_abc123",
        "conversation_id": 1,  # Will be set by actual conversation
        "direction": "in",
        "body_text": "Hello, this is a test message.",
    }


# -----------------------------------------------------------------------------
# Cleanup Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset the settings cache before each test."""
    from rediska_core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
