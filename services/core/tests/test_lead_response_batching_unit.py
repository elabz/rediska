"""Lead list author enrichment is batched: query count does not grow with page size."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from rediska_core.api.routes.leads import build_lead_response, build_lead_responses
from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
    Provider,
)

NOW = datetime(2026, 9, 17, 12, 0, 0)


@pytest.fixture
def provider(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()


def _author(db_session, n, *, posts=0, comments=0, signals=None):
    account = ExternalAccount(
        provider_id="reddit", external_username=f"test_author_{n}", remote_status="active"
    )
    db_session.add(account)
    db_session.flush()
    # An older snapshot that must NOT win.
    db_session.add(
        ProfileSnapshot(
            account_id=account.id,
            fetched_at=NOW - timedelta(days=5),
            signals_json={"karma": 1},
        )
    )
    if signals is not None:
        db_session.add(
            ProfileSnapshot(account_id=account.id, fetched_at=NOW, signals_json=signals)
        )
    for i in range(posts):
        db_session.add(
            ProfileItem(
                account_id=account.id, item_type="post", external_item_id=f"p{n}_{i}"
            )
        )
    for i in range(comments):
        db_session.add(
            ProfileItem(
                account_id=account.id, item_type="comment", external_item_id=f"c{n}_{i}"
            )
        )
    db_session.flush()
    return account


def _lead(db_session, n, account=None):
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/test_batch",
        external_post_id=f"test_batch_{n}",
        post_url=f"https://reddit.com/comments/test_batch_{n}",
        author_account_id=account.id if account else None,
        remote_visibility="unknown",
        created_at=NOW,
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def _count_queries(db_session, fn):
    engine = db_session.get_bind()
    statements: list[str] = []

    def before(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return result, len(statements)


def test_query_count_is_constant_in_page_size(db_session, provider):
    small = [_lead(db_session, n, _author(db_session, n, posts=1)) for n in range(2)]
    large = small + [
        _lead(db_session, n, _author(db_session, n, comments=2)) for n in range(2, 20)
    ]

    _, small_queries = _count_queries(db_session, lambda: build_lead_responses(small, db_session))
    _, large_queries = _count_queries(db_session, lambda: build_lead_responses(large, db_session))

    # accounts, latest snapshots, grouped item counts, copy clusters
    # (the copy lookup adds one more only when some post is in a cluster)
    assert small_queries == 4
    assert large_queries == 4


def test_author_info_matches_latest_snapshot_and_counts(db_session, provider):
    account = _author(
        db_session,
        1,
        posts=3,
        comments=2,
        signals={"karma": 4200, "created_at": "2020-01-01T00:00:00Z", "is_verified": True},
    )
    bare = _author(db_session, 2)
    no_author = _lead(db_session, 3)
    leads = [_lead(db_session, 1, account), _lead(db_session, 2, bare), no_author]

    responses = build_lead_responses(leads, db_session)

    first = responses[0]
    assert first.author_username == "test_author_1"
    assert first.author_info.karma == 4200
    assert first.author_info.is_verified is True
    assert first.author_info.post_count == 3
    assert first.author_info.comment_count == 2
    assert first.author_info.account_created_at.year == 2020

    second = responses[1]
    assert second.author_info.karma == 1  # only the older snapshot exists
    assert second.author_info.post_count is None
    assert second.author_info.comment_count is None

    assert responses[2].author_username is None
    assert responses[2].author_info is None


def test_list_shaped_signals_do_not_break_enrichment(db_session, provider):
    account = _author(db_session, 1, signals=[{"type": "interest", "value": "x"}])
    response = build_lead_response(_lead(db_session, 1, account), db_session)
    assert response.author_username == "test_author_1"
    assert response.author_info.karma is None
