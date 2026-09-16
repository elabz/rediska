"""Unit tests for external listing content resolution.

Covers:
1. Link-only body detection and URL matching/canonicalization
2. weheartbdsm parser against a saved-page fixture
3. Resolver failure fallbacks (timeout, 404, missing About)
4. Caching (positive, negative, cache hit skips fetch) and rate limiting
5. Hook behavior: save_lead resolves before persisting; browse feed
   substitution; ensure_lead_listing_content defensive re-check
"""

from pathlib import Path

import httpx
import pytest

from rediska_core.domain.services import external_listing
from rediska_core.domain.services.external_listing import (
    ExternalListingResolver,
    canonicalize_url,
    ensure_lead_listing_content,
    find_registered_host,
    is_link_only_body,
    parse_weheartbdsm,
)

FIXTURE = Path(__file__).parent / "fixtures" / "weheartbdsm_listing_8980.html"
LISTING_URL = "https://weheartbdsm.com/listings/8980?from=reddit"
CANONICAL_URL = "https://weheartbdsm.com/listings/8980"


# =============================================================================
# FAKES
# =============================================================================


class FakeRedis:
    """Minimal in-memory stand-in for the sync redis client."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key, ttl):
        pass


def make_resolver(handler, redis=None) -> ExternalListingResolver:
    """Resolver with a mocked HTTP transport and fake redis."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ExternalListingResolver(
        redis_client=redis if redis is not None else FakeRedis(),
        http_client=client,
    )


def fixture_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=FIXTURE.read_text())


# =============================================================================
# DETECTION / URL HANDLING
# =============================================================================


class TestLinkOnlyDetection:
    def test_empty_body_is_link_only(self):
        assert is_link_only_body(None, LISTING_URL)
        assert is_link_only_body("", LISTING_URL)
        assert is_link_only_body("   \n", LISTING_URL)

    def test_body_mirroring_url_is_link_only(self):
        assert is_link_only_body(LISTING_URL, LISTING_URL)
        assert is_link_only_body(f"  {LISTING_URL}  ", LISTING_URL)

    def test_real_body_is_not_link_only(self):
        assert not is_link_only_body("Actual post content here", LISTING_URL)

    def test_registered_host_matching(self):
        assert find_registered_host(LISTING_URL) is not None
        assert find_registered_host("https://www.weheartbdsm.com/listings/1") is not None
        assert find_registered_host("https://weheartbdsm.com/") is None
        assert find_registered_host("https://example.com/listings/8980") is None
        assert find_registered_host(None) is None
        assert find_registered_host("") is None

    def test_canonicalize_strips_query_and_fragment(self):
        assert canonicalize_url(LISTING_URL) == CANONICAL_URL
        assert canonicalize_url("HTTPS://WeHeartBDSM.com/listings/8980#x") == CANONICAL_URL


# =============================================================================
# PARSER
# =============================================================================


class TestWeheartbdsmParser:
    def test_extracts_full_body_from_fixture(self):
        text = parse_weheartbdsm(FIXTURE.read_text())
        assert text is not None
        assert text.startswith("[Listing details from weheartbdsm.com]")
        assert "About Me" in text
        # Full Inertia body, not the truncated JSON-LD description (154 chars)
        assert len(text) > 500
        assert "What I Enjoy" in text
        assert "\r" not in text  # line endings normalized

    def test_details_block_carries_structured_fields(self):
        from rediska_core.domain.services.external_listing import (
            parse_weheartbdsm_structured,
        )

        data = parse_weheartbdsm_structured(FIXTURE.read_text())
        assert data is not None
        assert (data.city, data.state, data.meet_type) == ("Testville", "Pennsylvania", "in_person")
        assert data.age == 34 and data.gender == "female" and data.position == "submissive"
        assert data.age_max_sought == 55
        assert data.kinks[0] == ("sourdough-baking", "into")

        text = data.as_text()
        header, _, body = text.partition("\n\n")
        assert "Location: Testville, Pennsylvania, United States (in person)" in header
        assert "Age: 34 | Gender: female | Position: submissive" in header
        assert "Seeking: male | Seeking position: dominant, switch | Sought age range: 30-55" in header
        assert "Kinks: sourdough-baking (into), cartography (curious)" in header
        assert "About Me" in body

    def test_details_block_omitted_when_no_structured_fields(self):
        from rediska_core.domain.services.external_listing import ListingData

        assert ListingData(body="just text").as_text() == "just text"
        assert ListingData(body="t", online_only=True).details_block().endswith("Location: (online only)")

    def test_falls_back_to_json_ld_description(self):
        html = (
            '<html><head><script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Article",'
            '"headline":"T","description":"About Me fallback text."}'
            "</script></head><body></body></html>"
        )
        assert parse_weheartbdsm(html) == "About Me fallback text."

    def test_returns_none_when_nothing_found(self):
        assert parse_weheartbdsm("<html><body><p>nope</p></body></html>") is None


# =============================================================================
# RESOLVER
# =============================================================================


class TestResolver:
    def test_resolves_and_caches_listing(self):
        redis = FakeRedis()
        resolver = make_resolver(fixture_handler, redis)
        text = resolver.resolve(LISTING_URL)
        assert text is not None and "About Me" in text
        # Positive result cached under canonical URL
        cached = redis.store[f"{external_listing.CACHE_KEY_PREFIX}{CANONICAL_URL}"]
        assert cached == text

    def test_cache_hit_skips_fetch(self):
        redis = FakeRedis()
        redis.store[f"{external_listing.CACHE_KEY_PREFIX}{CANONICAL_URL}"] = "cached text"

        def exploding_handler(request):  # pragma: no cover - must not be called
            raise AssertionError("HTTP fetch should not happen on cache hit")

        resolver = make_resolver(exploding_handler, redis)
        assert resolver.resolve(LISTING_URL) == "cached text"

    def test_negative_cache_returns_none(self):
        redis = FakeRedis()
        redis.store[f"{external_listing.CACHE_KEY_PREFIX}{CANONICAL_URL}"] = (
            external_listing.NEGATIVE_MARKER
        )
        resolver = make_resolver(fixture_handler, redis)
        assert resolver.resolve(LISTING_URL) is None

    def test_http_error_returns_none_and_negative_caches(self):
        redis = FakeRedis()
        resolver = make_resolver(lambda req: httpx.Response(404), redis)
        assert resolver.resolve(LISTING_URL) is None
        assert (
            redis.store[f"{external_listing.CACHE_KEY_PREFIX}{CANONICAL_URL}"]
            == external_listing.NEGATIVE_MARKER
        )

    def test_timeout_returns_none(self):
        def timeout_handler(request):
            raise httpx.ConnectTimeout("timed out")

        resolver = make_resolver(timeout_handler)
        assert resolver.resolve(LISTING_URL) is None

    def test_missing_about_returns_none(self):
        resolver = make_resolver(lambda req: httpx.Response(200, text="<html></html>"))
        assert resolver.resolve(LISTING_URL) is None

    def test_unregistered_url_is_not_fetched(self):
        def exploding_handler(request):  # pragma: no cover - must not be called
            raise AssertionError("should not fetch unregistered host")

        resolver = make_resolver(exploding_handler)
        assert resolver.resolve("https://example.com/listings/1") is None

    def test_rate_limit_skips_fetch_without_caching(self):
        redis = FakeRedis()
        resolver = make_resolver(fixture_handler, redis)
        # Exhaust this minute's budget
        import time

        key = (
            f"{external_listing.RATE_KEY_PREFIX}weheartbdsm:{int(time.time() // 60)}"
        )
        redis.counters[key] = external_listing.RATE_LIMIT_PER_MINUTE
        assert resolver.resolve(LISTING_URL) is None
        # Not negatively cached — a later encounter may retry
        assert f"{external_listing.CACHE_KEY_PREFIX}{CANONICAL_URL}" not in redis.store

    def test_maybe_resolve_prepends_details_to_real_body(self):
        """Authors paste the text on Reddit too; the listing still holds the facts."""
        resolver = make_resolver(fixture_handler)
        out = resolver.maybe_resolve_post_body("Hello from Reddit", LISTING_URL)
        assert out.startswith("[Listing details from weheartbdsm.com]")
        assert "Location: Testville, Pennsylvania" in out
        assert out.endswith("\n\nHello from Reddit")
        # idempotent on a second pass
        assert resolver.maybe_resolve_post_body(out, LISTING_URL) == out

    def test_maybe_resolve_leaves_real_body_untouched_for_unregistered_host(self):
        resolver = make_resolver(fixture_handler)
        assert resolver.maybe_resolve_post_body("Hello", "https://example.com/x") == "Hello"

    def test_maybe_resolve_falls_back_to_original_on_failure(self):
        resolver = make_resolver(lambda req: httpx.Response(500))
        assert resolver.maybe_resolve_post_body("", LISTING_URL) == ""


# =============================================================================
# HOOKS
# =============================================================================


@pytest.fixture
def resolver_with_fixture(monkeypatch):
    """Install a fixture-backed resolver as the process default."""
    resolver = make_resolver(fixture_handler)
    monkeypatch.setattr(external_listing, "_default_resolver", resolver)
    yield resolver
    monkeypatch.setattr(external_listing, "_default_resolver", None)


@pytest.fixture
def setup_provider(db_session):
    from rediska_core.domain.models import Provider

    provider = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(provider)
    db_session.flush()
    return provider


class TestSaveLeadResolution:
    """Integration: link-only post → save lead → resolved content persisted
    to lead_posts.body_text and profile_items.text_content BEFORE the save
    call returns (i.e. before auto-analyze can fire)."""

    def test_save_lead_persists_resolved_body_and_profile_item(
        self, db_session, setup_provider, resolver_with_fixture
    ):
        from rediska_core.domain.models import ProfileItem
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/bdsmpersonals",
            external_post_id="linkpost1",
            post_url=LISTING_URL,
            title="Brat seeking a Confident Wrangler",
            body_text="",  # link-only post
            author_username="listing_author",
        )
        assert lead.body_text is not None
        assert "About Me" in lead.body_text

        item = (
            db_session.query(ProfileItem)
            .filter(
                ProfileItem.account_id == lead.author_account_id,
                ProfileItem.external_item_id == "linkpost1",
            )
            .first()
        )
        assert item is not None
        assert "About Me" in item.text_content

    def test_save_lead_keeps_body_when_resolution_fails(
        self, db_session, setup_provider, monkeypatch
    ):
        resolver = make_resolver(lambda req: httpx.Response(404))
        monkeypatch.setattr(external_listing, "_default_resolver", resolver)

        from rediska_core.domain.services.leads import LeadsService

        lead = LeadsService(db=db_session).save_lead(
            provider_id="reddit",
            source_location="r/bdsmpersonals",
            external_post_id="linkpost2",
            post_url=LISTING_URL,
            title="T",
            body_text="",
            author_username="listing_author",
        )
        assert (lead.body_text or "") == ""


class TestBrowseFeedResolution:
    def test_browse_substitutes_listing_body(
        self, db_session, setup_provider, resolver_with_fixture
    ):
        from rediska_core.domain.services.browse import BrowseService

        class FakeClient:
            def browse_location(self, location, sort="hot", limit=25, after=None):
                return {
                    "posts": [
                        {
                            "id": "p1",
                            "title": "Link post",
                            "selftext": "",
                            "author": "a1",
                            "url": LISTING_URL,
                        },
                        {
                            "id": "p2",
                            "title": "Normal post",
                            "selftext": "already has content",
                            "author": "a2",
                            "url": "https://reddit.com/r/x/p2",
                        },
                    ],
                    "after": None,
                }

        service = BrowseService(db=db_session, provider_client=FakeClient())
        result = service.browse_location("reddit", "r/bdsmpersonals")
        by_id = {p["external_post_id"]: p for p in result["posts"]}
        assert "About Me" in by_id["p1"]["body_text"]
        assert by_id["p2"]["body_text"] == "already has content"


class TestEnsureLeadListingContent:
    """Defensive re-check used by the analysis paths (scout parity: same
    resolver runs in the worker before analyze_and_decide is enqueued)."""

    def test_resolves_stale_link_only_lead(
        self, db_session, setup_provider, resolver_with_fixture
    ):
        from rediska_core.domain.models import ExternalAccount, LeadPost, ProfileItem

        account = ExternalAccount(
            provider_id="reddit",
            external_username="stale_author",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/bdsmpersonals",
            external_post_id="stale1",
            post_url=LISTING_URL,
            title="T",
            body_text=None,  # saved before resolution existed
            author_account_id=account.id,
            status="saved",
            remote_visibility="unknown",
        )
        db_session.add(lead)
        db_session.flush()

        assert ensure_lead_listing_content(db_session, lead) is True
        assert lead.body_text is not None and "About Me" in lead.body_text
        item = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == account.id)
            .first()
        )
        assert item is not None and "About Me" in item.text_content

    def test_noop_for_lead_with_content(self, db_session, setup_provider):
        from rediska_core.domain.models import LeadPost

        lead = LeadPost(
            provider_id="reddit",
            source_location="r/x",
            external_post_id="ok1",
            post_url="https://reddit.com/r/x/ok1",
            body_text="has content",
            status="saved",
            remote_visibility="unknown",
        )
        db_session.add(lead)
        db_session.flush()
        assert ensure_lead_listing_content(db_session, lead) is False
        assert lead.body_text == "has content"
