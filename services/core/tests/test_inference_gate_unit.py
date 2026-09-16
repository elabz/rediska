"""Unit tests for the cross-process inference gate and inference retry logic."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rediska_core.domain.services.inference import (
    InferenceClient,
    InferenceConfig,
    InferenceError,
)
from rediska_core.infrastructure.inference_gate import InferenceGate, InferenceGateTimeout


class FakeRedis:
    """Minimal async Redis double: incr/decr/expire/get/set on one counter."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.fail = False

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key):
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key, ttl):
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = int(value)


@pytest.mark.asyncio
async def test_gate_serializes_across_holders():
    r = FakeRedis()
    gate_a = InferenceGate("redis://x", max_concurrent=1, redis_client=r)
    gate_b = InferenceGate("redis://x", max_concurrent=1, redis_client=r)

    assert await gate_a.acquire(timeout=1) == "redis"
    assert await r.get(gate_a.key) == 1

    # Second holder (simulating another worker process) must wait.
    with pytest.raises(InferenceGateTimeout):
        await gate_b.acquire(timeout=0.3)
    assert await r.get(gate_a.key) == 1  # failed attempt did not leak a slot

    await gate_a.release("redis")
    assert await gate_b.acquire(timeout=1) == "redis"
    await gate_b.release("redis")
    assert await r.get(gate_a.key) == 0


@pytest.mark.asyncio
async def test_gate_allows_up_to_max_concurrent():
    r = FakeRedis()
    gate = InferenceGate("redis://x", max_concurrent=2, redis_client=r)
    b1 = await gate.acquire(timeout=1)
    b2 = await gate.acquire(timeout=1)
    with pytest.raises(InferenceGateTimeout):
        await gate.acquire(timeout=0.2)
    await gate.release(b1)
    await gate.release(b2)


@pytest.mark.asyncio
async def test_gate_release_clamps_negative_counter():
    r = FakeRedis()
    gate = InferenceGate("redis://x", max_concurrent=1, redis_client=r)
    await gate.acquire(timeout=1)
    r.values[gate.key] = 0  # simulate TTL expiry mid-request
    await gate.release("redis")
    assert await r.get(gate.key) == 0


@pytest.mark.asyncio
async def test_gate_falls_back_to_local_when_redis_errors():
    r = FakeRedis()
    r.fail = True
    gate = InferenceGate("redis://x", max_concurrent=1, redis_client=r)
    assert await gate.acquire(timeout=1) == "local"
    with pytest.raises(InferenceGateTimeout):
        await gate.acquire(timeout=0.2)
    await gate.release("local")
    assert await gate.acquire(timeout=1) == "local"


@pytest.mark.asyncio
async def test_gate_without_redis_url_is_local():
    gate = InferenceGate(None, max_concurrent=1)
    assert await gate.acquire(timeout=1) == "local"
    await gate.release("local")


# ---------------------------------------------------------------------------
# Retry behaviour in the client
# ---------------------------------------------------------------------------


def _status_error(status: int, body: str = "", headers: dict | None = None):
    req = httpx.Request("POST", "http://llm/v1/chat/completions")
    resp = httpx.Response(status, request=req, text=body, headers=headers or {})
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


def _ok(content="hi"):
    req = httpx.Request("POST", "http://llm/v1/chat/completions")
    return httpx.Response(
        200,
        request=req,
        json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
    )


def _client(max_retries=4) -> InferenceClient:
    cfg = InferenceConfig(
        base_url="http://llm",
        timeout=5.0,
        max_retries=max_retries,
        retry_base_delay=0.01,
        retry_max_delay=0.02,
    )
    return InferenceClient(cfg)


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    client = _client()
    http = AsyncMock()
    responses = [_status_error(429, "cooldown"), _status_error(503), _ok()]

    async def post(path, json):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    http.post = post
    with patch.object(client, "_get_http_client", return_value=http), \
            patch("rediska_core.domain.services.inference.asyncio.sleep", new=AsyncMock()) as slp:
        out = await client._make_request([{"role": "user", "content": "x"}], 0.5, 10)
    assert out["choices"][0]["message"]["content"] == "hi"
    assert slp.await_count == 2
    assert await client._gate.inflight() == 0


@pytest.mark.asyncio
async def test_gives_up_after_max_retries():
    client = _client(max_retries=2)
    http = AsyncMock()
    http.post = AsyncMock(side_effect=_status_error(429))
    with patch.object(client, "_get_http_client", return_value=http), \
            patch("rediska_core.domain.services.inference.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(InferenceError) as ei:
            await client._make_request([{"role": "user", "content": "x"}], 0.5, 10)
    assert "429" in str(ei.value)
    assert http.post.await_count == 3  # 1 initial + 2 retries
    assert await client._gate.inflight() == 0  # slot released on failure


@pytest.mark.asyncio
async def test_no_retry_on_4xx_other_than_429():
    client = _client()
    http = AsyncMock()
    http.post = AsyncMock(side_effect=_status_error(400))
    with patch.object(client, "_get_http_client", return_value=http):
        with pytest.raises(InferenceError):
            await client._make_request([{"role": "user", "content": "x"}], 0.5, 10)
    assert http.post.await_count == 1


def test_retry_delay_honours_retry_after():
    client = _client()
    req = httpx.Request("POST", "http://llm")
    resp = httpx.Response(429, request=req, headers={"Retry-After": "90"})
    d = client._retry_delay(1, resp)
    assert 90 * 0.8 <= d <= 90 * 1.2


def test_retry_delay_doubles_and_caps():
    cfg = InferenceConfig(base_url="http://llm", retry_base_delay=10, retry_max_delay=25)
    client = InferenceClient(cfg)
    with patch("rediska_core.domain.services.inference.random.uniform", return_value=1.0):
        assert client._retry_delay(1, None) == 10
        assert client._retry_delay(2, None) == 20
        assert client._retry_delay(3, None) == 25
