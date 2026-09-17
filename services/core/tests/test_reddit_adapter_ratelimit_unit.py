"""Unit tests for RedditAdapter quota pacing and HTTP client reuse."""

from typing import Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rediska_core.providers.reddit.adapter import RedditAdapter

EMPTY_LISTING = {"data": {"children": [], "after": None}}


def make_adapter() -> RedditAdapter:
    return RedditAdapter(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        user_agent="Rediska/1.0 test",
    )


def listing_response(
    status: int = 200, remaining: Optional[str] = None, reset: Optional[str] = None
) -> httpx.Response:
    headers = {}
    if remaining is not None:
        headers["x-ratelimit-remaining"] = remaining
    if reset is not None:
        headers["x-ratelimit-reset"] = reset
    return httpx.Response(status, headers=headers, json=EMPTY_LISTING)


@pytest.fixture
def http():
    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        client_cls.return_value.__aenter__.return_value = instance
        yield client_cls, instance


@pytest.fixture
def sleep():
    with patch(
        "rediska_core.providers.reddit.adapter.asyncio.sleep", new_callable=AsyncMock
    ) as mock:
        yield mock


class TestHttpClientReuse:
    async def test_requests_share_one_client(self, http):
        client_cls, instance = http
        instance.get.return_value = listing_response()
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        await adapter.fetch_inbox_messages(cursor="t4_next")

        assert client_cls.call_count == 1
        assert instance.get.await_count == 2

    async def test_aclose_closes_the_client_and_a_later_request_opens_a_new_one(self, http):
        client_cls, instance = http
        instance.get.return_value = listing_response()
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        await adapter.aclose()

        # The entered client is closed (for a real httpx client, __aenter__ returns itself)
        instance.__aexit__.assert_awaited_once()
        await adapter.fetch_inbox_messages()
        assert client_cls.call_count == 2


class TestQuotaPacing:
    async def test_no_pause_while_quota_is_healthy(self, http, sleep):
        _, instance = http
        instance.get.return_value = listing_response(remaining="500", reset="300")
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        await adapter.fetch_inbox_messages()

        sleep.assert_not_awaited()

    async def test_low_quota_spreads_remaining_requests_over_the_window(self, http, sleep):
        _, instance = http
        instance.get.return_value = listing_response(remaining="4", reset="40")
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        sleep.assert_not_awaited()  # nothing known about the quota before the first response

        await adapter.fetch_inbox_messages()
        (delay,) = sleep.await_args.args
        assert 9.5 < delay <= 10.0  # ~40s left shared by 4 requests

    async def test_pause_is_capped(self, http, sleep):
        _, instance = http
        instance.get.return_value = listing_response(remaining="1", reset="590")
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        await adapter.fetch_inbox_messages()

        (delay,) = sleep.await_args.args
        assert delay == RedditAdapter.RATELIMIT_MAX_WAIT_SECONDS

    async def test_no_pause_once_the_window_has_reset(self, http, sleep):
        _, instance = http
        instance.get.return_value = listing_response(remaining="2", reset="5")
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        adapter._ratelimit_seen_at -= 10  # the 5s window ended since that response
        await adapter.fetch_inbox_messages()

        sleep.assert_not_awaited()

    async def test_429_waits_then_retries_once(self, http, sleep):
        _, instance = http
        instance.get.side_effect = [
            listing_response(429, remaining="0", reset="12"),
            listing_response(remaining="999", reset="600"),
        ]
        adapter = make_adapter()

        result = await adapter.fetch_inbox_messages()

        assert instance.get.await_count == 2
        assert sleep.await_count == 1
        (delay,) = sleep.await_args.args
        assert delay == 12.0
        assert result.items == []

    async def test_second_429_is_returned_to_the_caller(self, http, sleep):
        _, instance = http
        instance.get.side_effect = [listing_response(429), listing_response(429)]
        adapter = make_adapter()

        result = await adapter.fetch_inbox_messages()

        assert instance.get.await_count == 2
        assert result.items == []
        assert result.has_more is False

    async def test_malformed_headers_are_ignored(self, http, sleep):
        _, instance = http
        instance.get.return_value = listing_response(remaining="lots", reset="soon")
        adapter = make_adapter()

        await adapter.fetch_inbox_messages()
        await adapter.fetch_inbox_messages()

        assert adapter.ratelimit_remaining is None
        sleep.assert_not_awaited()
