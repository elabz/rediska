"""Unit tests for MessageSyncService paging, locking and failure isolation.

These run the real sync loop against the SQLite test database with a fake
Reddit adapter, so savepoints and per-page commits are exercised for real.
All message content here is synthetic.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from rediska_core.domain.models import Identity, Message, Provider
from rediska_core.domain.services.message_sync import SYNC_LOCK_KEY, MessageSyncService
from rediska_core.providers.base import PaginatedResult

MY_USERNAME = "test_me"
COUNTERPART = "test_counterpart"


def raw_message(msg_id: str, author: str = COUNTERPART, dest: str = MY_USERNAME) -> dict:
    return {
        "id": msg_id,
        "name": f"t4_{msg_id}",
        "author": author,
        "dest": dest,
        "body": f"synthetic body {msg_id}",
        "created_utc": 1_700_000_000.0,
        "first_message_name": "t4_thread",
    }


def pages_of(count: int, size: int = 100, prefix: str = "m") -> list[list[dict]]:
    return [[raw_message(f"{prefix}{p}_{i}") for i in range(size)] for p in range(count)]


class FakeAdapter:
    """Serves pre-built listing pages per endpoint, newest first."""

    def __init__(self, pages_by_endpoint: dict[str, list[list[dict]]]):
        self.pages_by_endpoint = pages_by_endpoint
        self.requests: list[tuple[str, Optional[str]]] = []
        self.closed = False

    async def fetch_inbox_messages(
        self, cursor: Optional[str] = None, limit: int = 100, endpoint: str = "/message/inbox"
    ) -> PaginatedResult[dict]:
        self.requests.append((endpoint, cursor))
        pages = self.pages_by_endpoint.get(endpoint, [])
        index = int(cursor) if cursor else 0
        if index >= len(pages):
            return PaginatedResult(items=[], next_cursor=None, has_more=False)
        has_more = index + 1 < len(pages)
        return PaginatedResult(
            items=pages[index],
            next_cursor=str(index + 1) if has_more else None,
            has_more=has_more,
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeLock:
    def __init__(self, redis: "FakeRedis", name: str):
        self.redis, self.name = redis, name

    def acquire(self, blocking: bool = True, blocking_timeout: Any = None) -> bool:
        if self.name in self.redis.held:
            return False
        self.redis.held.add(self.name)
        return True

    def reacquire(self) -> None:
        self.redis.renewals += 1

    def release(self) -> None:
        self.redis.held.discard(self.name)


class FakeRedis:
    def __init__(self) -> None:
        self.held: set[str] = set()
        self.renewals = 0

    def lock(self, name: str, timeout: Any = None) -> FakeLock:
        return FakeLock(self, name)


@pytest.fixture
def db_session(db_session):
    """The shared session, with SQLite savepoints behaving as they do on MySQL.

    pysqlite never emits BEGIN before a SAVEPOINT, so after a commit the next
    savepoint opens SQLite's own transaction and releasing it commits for real;
    a later rollback then cannot undo that message. SQLAlchemy's documented
    workaround hands transaction control back to SQLAlchemy for the test.
    """
    engine = db_session.get_bind()
    raw = engine.raw_connection()  # StaticPool: the one connection every session shares
    raw.driver_connection.isolation_level = None
    raw.close()

    def emit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    event.listen(engine, "begin", emit_begin)
    try:
        yield db_session
    finally:
        event.remove(engine, "begin", emit_begin)


@pytest.fixture
def identity(db_session) -> Identity:
    db_session.add(Provider(provider_id="reddit", display_name="Reddit"))
    identity = Identity(
        provider_id="reddit",
        external_username=MY_USERNAME,
        display_name="Test Identity",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    return identity


def make_service(db_session, adapter: FakeAdapter, redis: Any = None) -> MessageSyncService:
    """A real service with credentials, settings and Redis replaced by fakes."""
    service = MessageSyncService.__new__(MessageSyncService)
    service.db = db_session
    service.settings = MagicMock()
    service._redis = redis if redis is not None else FakeRedis()
    service._get_reddit_adapter = lambda identity: adapter  # type: ignore[method-assign]
    return service


def stored_ids(db_session) -> set[str]:
    return {m.external_message_id for m in db_session.query(Message).all()}


class TestPaging:
    async def test_routine_poll_stops_after_one_page_of_known_messages(self, db_session, identity):
        pages = pages_of(3)
        await make_service(db_session, FakeAdapter({"/message/inbox": pages})).sync_inbox_only()

        adapter = FakeAdapter({"/message/inbox": pages})
        result = await make_service(db_session, adapter).sync_inbox_only()

        assert adapter.requests == [("/message/inbox", None)]
        assert result.new_messages == 0
        assert not result.aborted

    async def test_page_cap_stops_paging(self, db_session, identity):
        adapter = FakeAdapter({"/message/inbox": pages_of(8)})

        result = await make_service(db_session, adapter).sync_inbox_only(max_pages=5)

        assert len(adapter.requests) == 5
        assert result.pages_fetched == 5
        assert result.new_messages == 500

    async def test_no_cap_walks_to_the_end(self, db_session, identity):
        adapter = FakeAdapter({"/message/inbox": pages_of(3, size=20)})

        result = await make_service(db_session, adapter).sync_reddit_messages(inbox_only=True)

        assert len(adapter.requests) == 3
        assert result.new_messages == 60

    async def test_sent_only_sync_reads_only_the_sent_folder(self, db_session, identity):
        adapter = FakeAdapter({
            "/message/inbox": [[raw_message("in1")]],
            "/message/sent": [[raw_message("out1", author=MY_USERNAME, dest=COUNTERPART)]],
        })

        await make_service(db_session, adapter).sync_sent_only()

        assert [endpoint for endpoint, _ in adapter.requests] == ["/message/sent"]
        assert stored_ids(db_session) == {"out1"}


class TestFailureIsolation:
    async def test_concurrent_duplicate_insert_does_not_poison_the_run(self, db_session, identity):
        await make_service(
            db_session, FakeAdapter({"/message/inbox": [[raw_message("dup")]]})
        ).sync_inbox_only()

        service = make_service(db_session, FakeAdapter({
            "/message/inbox": [[raw_message("new1"), raw_message("dup"), raw_message("new2")]],
        }))
        original_create = service._create_message_if_not_exists
        raced: list[bool] = []

        def create_losing_a_race(**kwargs):
            if kwargs["external_message_id"] == "dup" and not raced:
                raced.append(True)
                # The other writer wins between our existence check and our insert
                db_session.add(Message(
                    provider_id="reddit",
                    external_message_id="dup",
                    conversation_id=kwargs["conversation"].id,
                    direction="in",
                    sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    remote_visibility="visible",
                ))
                db_session.flush()
            return original_create(**kwargs)

        service._create_message_if_not_exists = create_losing_a_race  # type: ignore[method-assign]
        result = await service.sync_inbox_only()

        assert raced
        assert not result.aborted
        assert result.errors == []
        assert result.new_messages == 2
        assert stored_ids(db_session) == {"dup", "new1", "new2"}
        assert db_session.query(Message).filter_by(external_message_id="dup").count() == 1

    async def test_database_failure_stops_the_run_and_keeps_earlier_pages(
        self, db_session, identity
    ):
        redis = FakeRedis()
        adapter = FakeAdapter({"/message/inbox": [
            [raw_message("p0_a"), raw_message("p0_b")],
            [raw_message("p1_a"), raw_message("p1_b")],
            [raw_message("p2_a")],
        ]})
        service = make_service(db_session, adapter, redis)
        original_create = service._create_message_if_not_exists

        def create_hitting_a_deadlock(**kwargs):
            if kwargs["external_message_id"] == "p1_b":
                raise OperationalError("INSERT INTO messages", {}, Exception("Deadlock found"))
            return original_create(**kwargs)

        service._create_message_if_not_exists = create_hitting_a_deadlock  # type: ignore[method-assign]
        result = await service.sync_inbox_only()

        assert result.aborted
        assert len(adapter.requests) == 2, "must not page on after a database failure"
        assert stored_ids(db_session) == {"p0_a", "p0_b"}, "first page kept, failed page rolled back"
        assert any("p1_b" in error for error in result.errors)
        assert redis.held == set()
        assert adapter.closed

    async def test_unparseable_message_skips_only_that_message(self, db_session, identity):
        broken = {**raw_message("bad"), "created_utc": "not-a-timestamp"}
        adapter = FakeAdapter({"/message/inbox": [[raw_message("a"), broken, raw_message("b")]]})

        result = await make_service(db_session, adapter).sync_inbox_only()

        assert not result.aborted
        assert stored_ids(db_session) == {"a", "b"}
        assert any("bad" in error for error in result.errors)


class TestSingleFlight:
    async def test_run_is_skipped_while_another_sync_holds_the_lock(self, db_session, identity):
        redis = FakeRedis()
        redis.held.add(SYNC_LOCK_KEY.format(identity_id=identity.id))
        adapter = FakeAdapter({"/message/inbox": [[raw_message("m1")]]})

        result = await make_service(db_session, adapter, redis).sync_inbox_only()

        assert result.skipped
        assert adapter.requests == []
        assert stored_ids(db_session) == set()

    async def test_lock_is_renewed_per_page_and_released(self, db_session, identity):
        redis = FakeRedis()
        adapter = FakeAdapter({"/message/inbox": pages_of(2, size=5)})

        result = await make_service(db_session, adapter, redis).sync_inbox_only()

        assert not result.skipped
        assert redis.renewals == 2
        assert redis.held == set()
        assert adapter.closed

    async def test_sync_runs_unlocked_when_redis_is_unreachable(self, db_session, identity):
        class UnreachableRedis:
            def lock(self, name: str, timeout: Any = None):
                raise ConnectionError("redis unreachable")

        adapter = FakeAdapter({"/message/inbox": [[raw_message("m1")]]})

        result = await make_service(db_session, adapter, UnreachableRedis()).sync_inbox_only()

        assert not result.skipped
        assert stored_ids(db_session) == {"m1"}
