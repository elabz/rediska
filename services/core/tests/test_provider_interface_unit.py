"""Unit tests for the provider interface (ABC) and its real implementations."""

import inspect

import pytest

from rediska_core.providers.base import ProviderAdapter
from rediska_core.providers.reddit.adapter import RedditAdapter


class TestProviderAdapterInterface:
    """Tests for ProviderAdapter interface."""

    def test_adapter_is_abstract(self):
        """ProviderAdapter should not be instantiable directly."""
        with pytest.raises(TypeError):
            ProviderAdapter()

    def test_adapter_requires_provider_id(self):
        """Adapter implementations must define provider_id."""
        class IncompleteAdapter(ProviderAdapter):
            pass

        with pytest.raises(TypeError):
            IncompleteAdapter()

    def test_adapter_subclass_must_implement_methods(self):
        """Adapter subclasses must implement required methods."""
        class MinimalAdapter(ProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "test"

        # Should still fail because abstract methods not implemented
        with pytest.raises(TypeError):
            MinimalAdapter()


class TestRedditAdapterConformance:
    """The shipped RedditAdapter must satisfy the ProviderAdapter contract.

    These tests deliberately exercise the *real* adapter class rather than a
    stub, so deleting or renaming a method on RedditAdapter fails the suite.
    """

    def test_reddit_adapter_is_a_provider_adapter(self):
        assert issubclass(RedditAdapter, ProviderAdapter)

    def test_reddit_adapter_is_concrete(self):
        """No abstract methods may be left unimplemented (else it can't be instantiated)."""
        assert RedditAdapter.__abstractmethods__ == frozenset()

    @pytest.mark.parametrize("name", sorted(ProviderAdapter.__abstractmethods__))
    def test_reddit_adapter_overrides_abstract_member(self, name):
        """Each abstract member is defined on RedditAdapter itself, not inherited."""
        assert name in RedditAdapter.__dict__, f"RedditAdapter does not define {name}"
        assert getattr(RedditAdapter, name) is not getattr(ProviderAdapter, name)

    @pytest.mark.parametrize("name", sorted(ProviderAdapter.__abstractmethods__))
    def test_reddit_adapter_signature_is_compatible(self, name):
        """The override accepts at least the ABC's parameters, in the same order.

        Extra trailing parameters are allowed (browse_location adds sort/
        time_filter/query), but callers coding to the ABC must keep working.
        """
        base = getattr(ProviderAdapter, name)
        impl = getattr(RedditAdapter, name)
        if isinstance(base, property):
            base, impl = base.fget, impl.fget

        base_params = list(inspect.signature(base).parameters)
        impl_params = list(inspect.signature(impl).parameters)

        assert impl_params[: len(base_params)] == base_params
        # Any widening must be optional so ABC-shaped calls still bind.
        extra = list(inspect.signature(impl).parameters.values())[len(base_params):]
        assert all(p.default is not inspect.Parameter.empty for p in extra)

    def test_async_methods_stay_async(self):
        """Awaitable contract methods must remain coroutine functions."""
        for name in ProviderAdapter.__abstractmethods__:
            base = getattr(ProviderAdapter, name)
            if isinstance(base, property):
                continue
            assert inspect.iscoroutinefunction(base) == inspect.iscoroutinefunction(
                getattr(RedditAdapter, name)
            ), f"{name} async-ness diverges from the ABC"

