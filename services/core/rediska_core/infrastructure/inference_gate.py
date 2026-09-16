"""Cross-process concurrency gate for LLM inference calls.

The local llama.cpp backend serves one request at a time (unless started with
``--parallel``); when several land at once it answers 503, and the LiteLLM
gateway in front of it then puts the deployment into a cooldown during which
every call gets 429. Rediska fans out five dimension agents plus two profile
summaries per lead across four Celery worker processes, so without a gate an
analysis is almost guaranteed to trip that cooldown.

``InferenceGate`` is a Redis-backed counting semaphore shared by every process
that talks to the inference endpoint. Callers wait (with polling) until a slot
is free. If Redis is unreachable it degrades to a process-local
``asyncio.Semaphore`` so inference still works, just without cross-process
coordination.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

INFLIGHT_KEY = "rediska:inference:inflight"


class InferenceGateTimeout(Exception):
    """Raised when no inference slot became free within the wait budget."""


class InferenceGate:
    """Counting semaphore over Redis, shared across worker processes.

    Args:
        redis_url: Redis URL; ``None`` disables Redis and uses the local fallback.
        max_concurrent: Number of simultaneous inference requests allowed globally.
        slot_ttl: Seconds after which an inflight count expires (guards against
            leaks from crashed processes). Should exceed the inference timeout.
        key: Redis key holding the inflight counter.
        redis_client: Optional pre-built ``redis.asyncio`` client (tests).
    """

    def __init__(
        self,
        redis_url: Optional[str],
        max_concurrent: int = 1,
        slot_ttl: int = 600,
        key: str = INFLIGHT_KEY,
        redis_client: Any = None,
    ) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.slot_ttl = max(30, int(slot_ttl))
        self.key = key
        self._redis_url = redis_url
        self._redis = redis_client
        self._redis_failed = False
        self._local = asyncio.Semaphore(self.max_concurrent)

    # -- redis ---------------------------------------------------------------

    def _get_redis(self) -> Any:
        if self._redis is not None or self._redis_failed or not self._redis_url:
            return self._redis
        try:
            import redis.asyncio as redis_lib

            self._redis = redis_lib.Redis.from_url(
                self._redis_url, socket_timeout=5, socket_connect_timeout=5
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Inference gate: Redis unavailable, using local semaphore: {e}")
            self._redis_failed = True
        return self._redis

    async def _try_acquire_redis(self, r: Any) -> bool:
        count = await r.incr(self.key)
        await r.expire(self.key, self.slot_ttl)
        if count > self.max_concurrent:
            await r.decr(self.key)
            return False
        return True

    async def _release_redis(self, r: Any) -> None:
        remaining = await r.decr(self.key)
        if remaining < 0:
            # Counter drifted (TTL expiry mid-request); clamp so we never
            # under-count and let more than max_concurrent through.
            await r.set(self.key, 0, ex=self.slot_ttl)

    # -- public --------------------------------------------------------------

    async def acquire(self, timeout: float = 900.0) -> str:
        """Block until a slot is free. Returns the backend used ("redis"/"local")."""
        r = self._get_redis()
        if r is not None:
            start = time.monotonic()
            attempt = 0
            while True:
                try:
                    if await self._try_acquire_redis(r):
                        if attempt:
                            logger.info(
                                f"Inference gate: slot acquired after "
                                f"{time.monotonic() - start:.1f}s wait"
                            )
                        return "redis"
                except Exception as e:
                    logger.warning(
                        f"Inference gate: Redis error, falling back to local semaphore: {e}"
                    )
                    self._redis_failed = True
                    self._redis = None
                    break
                attempt += 1
                if time.monotonic() - start >= timeout:
                    raise InferenceGateTimeout(
                        f"No inference slot free after {timeout:.0f}s "
                        f"(max_concurrent={self.max_concurrent})"
                    )
                # Poll with mild jitter; requests take seconds, so 0.5-1.5s is fine.
                await asyncio.sleep(0.5 + random.random())

        try:
            await asyncio.wait_for(self._local.acquire(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise InferenceGateTimeout(
                f"No inference slot free after {timeout:.0f}s (local)"
            ) from e
        return "local"

    async def release(self, backend: str) -> None:
        if backend == "redis":
            r = self._get_redis()
            if r is not None:
                try:
                    await self._release_redis(r)
                    return
                except Exception as e:
                    logger.warning(f"Inference gate: failed to release Redis slot: {e}")
                    return
        self._local.release()

    async def inflight(self) -> int:
        """Current global inflight count (best effort; 0 if Redis is unavailable)."""
        r = self._get_redis()
        if r is None:
            return self.max_concurrent - self._local._value  # type: ignore[attr-defined]
        try:
            raw = await r.get(self.key)
            return int(raw or 0)
        except Exception:
            return 0


__all__ = ["InferenceGate", "InferenceGateTimeout", "INFLIGHT_KEY"]
