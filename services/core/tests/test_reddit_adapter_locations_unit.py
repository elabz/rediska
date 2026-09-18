"""Unit tests for RedditAdapter location search and location info (source-discovery).

All payloads are synthetic.
"""

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rediska_core.providers.base import ProviderAdapter, ProviderLocation
from rediska_core.providers.reddit.adapter import RedditAdapter, RedditAPIError


def make_adapter() -> RedditAdapter:
    return RedditAdapter(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        user_agent="Rediska/1.0 test",
    )


def subreddit(name: str, **extra: Any) -> dict:
    data = {
        "display_name": name,
        "display_name_prefixed": f"r/{name}",
        "title": f"{name} title",
        "public_description": f"About {name}",
        "subscribers": 1200,
        "accounts_active": 15,
        "over18": False,
        "created_utc": 1600000000,
        "subreddit_type": "public",
    }
    data.update(extra)
    return data


def response(
    status: int = 200,
    body: Any = None,
    remaining: Optional[str] = None,
    reset: Optional[str] = None,
) -> httpx.Response:
    headers = {}
    if remaining is not None:
        headers["x-ratelimit-remaining"] = remaining
    if reset is not None:
        headers["x-ratelimit-reset"] = reset
    return httpx.Response(status, headers=headers, json=body if body is not None else {})


@pytest.fixture
def http():
    with patch("httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        client_cls.return_value.__aenter__.return_value = instance
        yield instance


@pytest.fixture
def sleep():
    with patch(
        "rediska_core.providers.reddit.adapter.asyncio.sleep", new_callable=AsyncMock
    ) as mock:
        yield mock


class TestSearchLocations:
    async def test_maps_results_and_keeps_nsfw(self, http):
        http.get.return_value = response(
            body={
                "data": {
                    "children": [
                        {"kind": "t5", "data": subreddit("test_ropes", over18=True)},
                        {"kind": "t5", "data": subreddit("test_knots")},
                        {"kind": "t3", "data": {"id": "not_a_subreddit"}},
                    ]
                }
            }
        )

        results = await make_adapter().search_locations("rope personals", limit=25)

        assert [r.name for r in results] == ["r/test_ropes", "r/test_knots"]
        first = results[0]
        assert isinstance(first, ProviderLocation)
        assert first.is_nsfw is True  # never filtered out
        assert first.description == "About test_ropes"
        assert first.member_count == 1200
        assert first.active_count == 15
        assert first.created_at is not None

        endpoint = http.get.await_args.args[0]
        params = http.get.await_args.kwargs["params"]
        assert endpoint.endswith("/subreddits/search")
        assert params["q"] == "rope personals"
        assert params["include_over_18"] == "on"
        assert params["limit"] == 25

    async def test_limit_is_respected(self, http):
        http.get.return_value = response(
            body={"data": {"children": [
                {"kind": "t5", "data": subreddit(f"test_{i}")} for i in range(5)
            ]}}
        )

        results = await make_adapter().search_locations("x", limit=2)

        assert len(results) == 2

    async def test_error_status_raises(self, http):
        http.get.return_value = response(status=500)

        with pytest.raises(RedditAPIError):
            await make_adapter().search_locations("x")


class TestGetLocationInfo:
    async def test_returns_summary(self, http):
        http.get.return_value = response(body={"kind": "t5", "data": subreddit("test_sub")})

        info = await make_adapter().get_location_info("r/test_sub")

        assert info is not None
        assert info.name == "r/test_sub"
        assert http.get.await_args.args[0].endswith("/r/test_sub/about")

    @pytest.mark.parametrize(
        "status,body",
        [
            (403, {"reason": "private"}),
            (404, {"reason": "banned"}),
            (404, {}),
        ],
    )
    async def test_unavailable_returns_none(self, http, status, body):
        http.get.return_value = response(status=status, body=body)

        assert await make_adapter().get_location_info("test_gone") is None

    async def test_search_listing_for_missing_community_returns_none(self, http):
        http.get.return_value = response(
            body={"kind": "Listing", "data": {"children": []}}
        )

        assert await make_adapter().get_location_info("test_missing") is None

    async def test_private_type_returns_none(self, http):
        http.get.return_value = response(
            body={"kind": "t5", "data": subreddit("test_priv", subreddit_type="private")}
        )

        assert await make_adapter().get_location_info("test_priv") is None


class TestRateLimitPacing:
    async def test_lookup_waits_when_quota_is_nearly_exhausted(self, http, sleep):
        http.get.return_value = response(
            body={"kind": "t5", "data": subreddit("test_sub")}, remaining="2", reset="100"
        )
        adapter = make_adapter()

        await adapter.get_location_info("test_sub")  # records the low quota
        await adapter.search_locations("x")  # must be paced, not sent at once

        assert sleep.await_count == 1
        assert sleep.await_args.args[0] > 0


class TestDefaultContract:
    async def test_providers_opt_in(self):
        """The base implementations raise, so other providers opt in explicitly."""
        stub = SimpleNamespace(provider_id="test_provider")

        with pytest.raises(NotImplementedError):
            await ProviderAdapter.search_locations(stub, "x")  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError):
            await ProviderAdapter.get_location_info(stub, "x")  # type: ignore[arg-type]
