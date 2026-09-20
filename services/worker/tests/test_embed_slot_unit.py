"""The embed slot must heal after a leak, not deadlock on one.

A worker killed mid-embed leaves its slot incremented. The TTL on the counter
is the only thing that ever gives that slot back, so anything that refreshes
the TTL without holding the slot turns an ordinary leak into a permanent one.

This happened twice: first in the inference gate, then here, where a backfill
spun for hours at 58k of 251k documents because every waiter kept pushing the
expiry of the counter it was waiting on out of reach.
"""

import time
from types import SimpleNamespace

from rediska_worker.tasks import embed


class FakeRedis:
    """Just enough Redis to exercise the slot protocol."""

    def __init__(self, start=0):
        self.value = start
        self.expire_calls = 0

    def incr(self, key):
        self.value += 1
        return self.value

    def decr(self, key):
        self.value -= 1
        return self.value

    def expire(self, key, ttl):
        self.expire_calls += 1
        return True

    def set(self, key, value):
        self.value = value
        return True


def settings(max_concurrent=1):
    return SimpleNamespace(embed_max_concurrent=max_concurrent, redis_url="redis://x")


def use_slot(monkeypatch, client, sleep_calls=None):
    monkeypatch.setattr(embed, "_redis", lambda _s: client)
    if sleep_calls is not None:
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    with embed._embed_slot(settings()):
        pass


class TestSlotAccounting:
    def test_taking_and_releasing_a_slot_balances(self, monkeypatch):
        client = FakeRedis()

        use_slot(monkeypatch, client)

        assert client.value == 0
        assert client.expire_calls == 1

    def test_a_waiter_never_refreshes_the_ttl(self, monkeypatch):
        """The leak-healing property: only the holder may set the TTL."""
        client = FakeRedis(start=1)  # a leaked slot nobody holds
        sleeps: list[float] = []

        # Wind the clock forward so the acquire loop gives up immediately
        # rather than waiting out its real 120-second window.
        clock = iter([0.0, 1000.0, 2000.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(clock))

        use_slot(monkeypatch, client, sleeps)

        # It failed open (the body still ran) without ever touching the TTL,
        # so the leaked counter can still expire on its own.
        assert client.expire_calls == 0
        # And it put back what it borrowed while probing.
        assert client.value == 1

    def test_failing_open_does_not_decrement_someone_elses_slot(self, monkeypatch):
        client = FakeRedis(start=1)
        clock = iter([0.0, 1000.0, 2000.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(clock))

        use_slot(monkeypatch, client, [])

        assert client.value == 1

    def test_a_negative_counter_is_reset_not_left_negative(self, monkeypatch):
        client = FakeRedis(start=0)
        monkeypatch.setattr(embed, "_redis", lambda _s: client)

        with embed._embed_slot(settings()):
            client.value = 0  # something else reset it underneath us

        assert client.value == 0

    def test_no_redis_means_no_gate(self, monkeypatch):
        """Pacing is best-effort; it must never stop the pipeline."""
        monkeypatch.setattr(embed, "_redis", lambda _s: None)

        ran = False
        with embed._embed_slot(settings()):
            ran = True

        assert ran
