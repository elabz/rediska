"""Database infrastructure for Rediska Core."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from rediska_core.config import get_settings


def get_sync_engine():
    """Get synchronous database engine."""
    settings = get_settings()
    return create_engine(
        settings.mysql_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


def get_async_engine():
    """Get async database engine."""
    settings = get_settings()
    # Convert mysql+pymysql to mysql+aiomysql for async
    async_url = settings.mysql_url.replace("pymysql", "aiomysql")
    return create_async_engine(
        async_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


# Session factories
_sync_engine = None
_async_engine = None
_sync_session_factory = None
_async_session_factory = None


def get_sync_session_factory() -> sessionmaker[Session]:
    """Get synchronous session factory (singleton)."""
    global _sync_engine, _sync_session_factory
    if _sync_session_factory is None:
        _sync_engine = get_sync_engine()
        _sync_session_factory = sessionmaker(
            bind=_sync_engine,
            autocommit=False,
            autoflush=False,
        )
    return _sync_session_factory


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get async session factory (singleton)."""
    global _async_engine, _async_session_factory
    if _async_session_factory is None:
        _async_engine = get_async_engine()
        _async_session_factory = async_sessionmaker(
            bind=_async_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _async_session_factory


def get_db_session():
    """Get a synchronous database session (for use in sync contexts)."""
    session_factory = get_sync_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session (for use in async contexts)."""
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def async_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions."""
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
