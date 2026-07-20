"""Resolve external listing links into post body text.

Some subreddits (e.g. r/bdsmpersonals) no longer carry post content in the
Reddit post body: the post is link-only and points to an external listing page
such as https://weheartbdsm.com/listings/8980?from=reddit. This service fetches
the listing page for registered hosts, extracts the About/description text, and
substitutes it as the post body — stored as if it were the content of the
corresponding Reddit post.

Guarantees:
- Best-effort: any failure returns None / the original body; never raises.
- Polite: bounded timeout, identifying User-Agent, per-host rate limit.
- Cached: resolved text cached in Redis by canonical URL (positive ~7 days,
  negative ~1 hour) so repeat encounters don't re-fetch.

Usage:
    from rediska_core.domain.services.external_listing import get_resolver

    body = get_resolver().maybe_resolve_post_body(body_text, post_url)
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from rediska_core.config import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

FETCH_TIMEOUT_SECONDS = 10.0
POSITIVE_CACHE_TTL_SECONDS = 7 * 24 * 3600  # resolved text: ~7 days
NEGATIVE_CACHE_TTL_SECONDS = 3600  # failed resolution: ~1 hour
RATE_LIMIT_PER_MINUTE = 30  # per listing host
CACHE_KEY_PREFIX = "rediska:listing:body:"
RATE_KEY_PREFIX = "rediska:listing:rl:"
NEGATIVE_MARKER = "\x00unresolved"


# =============================================================================
# PARSERS
# =============================================================================


def parse_weheartbdsm(html: str) -> Optional[str]:
    """Extract the About/body text from a weheartbdsm.com listing page.

    The page is an Inertia.js app: the full listing lives in the JSON
    `data-page` attribute at props.listing.body. A truncated fallback is
    available in the JSON-LD Article block's description.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Primary: Inertia data-page JSON -> props.listing.body (full text)
    tag = soup.find(attrs={"data-page": True})
    if tag is not None:
        try:
            page = json.loads(tag["data-page"])
            body = page.get("props", {}).get("listing", {}).get("body")
            if isinstance(body, str) and body.strip():
                return _normalize_text(body)
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning("weheartbdsm: failed to parse data-page JSON")

    # Fallback: JSON-LD Article description (may be truncated)
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Article":
            description = data.get("description")
            if isinstance(description, str) and description.strip():
                return _normalize_text(description)

    return None


def _normalize_text(text: str) -> str:
    """Normalize extracted listing text (line endings, stray whitespace)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =============================================================================
# HOST REGISTRY
# =============================================================================


@dataclass(frozen=True)
class ListingHost:
    """A supported external listing host."""

    name: str
    url_pattern: re.Pattern
    parser: Callable[[str], Optional[str]]


LISTING_HOSTS: list[ListingHost] = [
    ListingHost(
        name="weheartbdsm",
        url_pattern=re.compile(
            r"^https?://(www\.)?weheartbdsm\.com/listings/\d+", re.IGNORECASE
        ),
        parser=parse_weheartbdsm,
    ),
]


def find_registered_host(url: Optional[str]) -> Optional[ListingHost]:
    """Return the registered host matching the URL, if any."""
    if not url:
        return None
    for host in LISTING_HOSTS:
        if host.url_pattern.match(url.strip()):
            return host
    return None


def canonicalize_url(url: str) -> str:
    """Canonical fetch/cache URL: strip query (tracking params) and fragment."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def is_link_only_body(body_text: Optional[str], post_url: Optional[str]) -> bool:
    """True when a post body is empty or merely mirrors the post's own URL."""
    if body_text is None or not body_text.strip():
        return True
    if post_url and body_text.strip() == post_url.strip():
        return True
    return False


# =============================================================================
# RESOLVER
# =============================================================================


class ExternalListingResolver:
    """Fetches and caches About text for registered external listing hosts."""

    def __init__(self, redis_client=None, http_client: Optional[httpx.Client] = None):
        """Both clients are injectable for tests; lazily created otherwise."""
        self._redis = redis_client
        self._redis_failed = False
        self._http = http_client

    # -- infrastructure -------------------------------------------------------

    def _get_redis(self):
        if self._redis is not None or self._redis_failed:
            return self._redis
        try:
            import redis as redis_lib

            self._redis = redis_lib.Redis.from_url(
                get_settings().redis_url, decode_responses=True, socket_timeout=2
            )
        except Exception:
            logger.warning("Listing resolver: Redis unavailable, caching disabled")
            self._redis_failed = True
        return self._redis

    def _user_agent(self) -> str:
        return get_settings().provider_reddit_user_agent or "Rediska/1.0"

    def _check_rate_limit(self, host: ListingHost) -> bool:
        """Sliding-minute counter per host. Allows when Redis is unavailable."""
        client = self._get_redis()
        if client is None:
            return True
        try:
            import time

            key = f"{RATE_KEY_PREFIX}{host.name}:{int(time.time() // 60)}"
            count = int(client.incr(key))  # type: ignore[arg-type]  # sync client returns int
            client.expire(key, 120)
            return count <= RATE_LIMIT_PER_MINUTE
        except Exception:
            return True

    def _cache_get(self, key: str) -> Optional[str]:
        client = self._get_redis()
        if client is None:
            return None
        try:
            value = client.get(key)
            return value if isinstance(value, str) else None
        except Exception:
            return None

    def _cache_set(self, key: str, value: str, ttl: int) -> None:
        client = self._get_redis()
        if client is None:
            return
        try:
            client.set(key, value, ex=ttl)
        except Exception:
            pass

    # -- public API -----------------------------------------------------------

    def resolve(self, url: Optional[str]) -> Optional[str]:
        """Resolve a listing URL to its About text, or None. Never raises."""
        host = find_registered_host(url)
        if host is None:
            return None
        canonical = canonicalize_url(url)  # type: ignore[arg-type]
        cache_key = f"{CACHE_KEY_PREFIX}{canonical}"

        cached = self._cache_get(cache_key)
        if cached is not None:
            return None if cached == NEGATIVE_MARKER else cached

        if not self._check_rate_limit(host):
            logger.warning("Listing resolver: rate limit hit for %s, skipping", host.name)
            return None  # not cached: retry on a later encounter

        text: Optional[str] = None
        try:
            http = self._http or httpx.Client(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent()},
            )
            try:
                response = http.get(canonical)
                if response.status_code == 200:
                    text = host.parser(response.text)
                else:
                    logger.warning(
                        "Listing resolver: %s returned %d", canonical, response.status_code
                    )
            finally:
                if self._http is None:
                    http.close()
        except Exception as exc:
            logger.warning("Listing resolver: fetch failed for %s: %s", canonical, exc)

        if text:
            self._cache_set(cache_key, text, POSITIVE_CACHE_TTL_SECONDS)
        else:
            self._cache_set(cache_key, NEGATIVE_MARKER, NEGATIVE_CACHE_TTL_SECONDS)
        return text

    def maybe_resolve_post_body(
        self, body_text: Optional[str], post_url: Optional[str]
    ) -> Optional[str]:
        """Return the resolved listing text for a link-only post, else the body.

        Only fetches when the body is link-only AND the URL matches a registered
        host. On any failure the original body is returned unchanged.
        """
        if not is_link_only_body(body_text, post_url):
            return body_text
        if find_registered_host(post_url) is None:
            return body_text
        resolved = self.resolve(post_url)
        return resolved if resolved else body_text


# =============================================================================
# MODULE-LEVEL DEFAULT (hooks import these; tests may monkeypatch)
# =============================================================================

_default_resolver: Optional[ExternalListingResolver] = None


def get_resolver() -> ExternalListingResolver:
    """Process-wide default resolver instance."""
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = ExternalListingResolver()
    return _default_resolver


def maybe_resolve_post_body(
    body_text: Optional[str], post_url: Optional[str]
) -> Optional[str]:
    """Convenience wrapper over the default resolver. Never raises."""
    try:
        return get_resolver().maybe_resolve_post_body(body_text, post_url)
    except Exception as exc:  # defense-in-depth: hooks must never fail ingestion
        logger.warning("Listing resolver: unexpected error: %s", exc)
        return body_text


def ensure_lead_listing_content(db, lead) -> bool:
    """Defensive re-check used by analysis paths.

    If the stored lead body is still link-only and its URL matches a registered
    host, resolve once, persist to the lead and the author's profile_item, and
    return True if the body was updated.
    """
    try:
        if not is_link_only_body(lead.body_text, lead.post_url):
            return False
        if find_registered_host(lead.post_url) is None:
            return False
        resolved = get_resolver().resolve(lead.post_url)
        if not resolved:
            return False
        lead.body_text = resolved
        if lead.author_account_id:
            from rediska_core.domain.services.profile_item_utils import (
                upsert_profile_item_from_post,
            )

            upsert_profile_item_from_post(
                db=db,
                account_id=lead.author_account_id,
                external_post_id=lead.external_post_id,
                title=lead.title,
                body_text=resolved,
                source_location=lead.source_location,
                post_created_at=lead.post_created_at,
            )
        db.flush()
        return True
    except Exception as exc:
        logger.warning("Listing resolver: ensure_lead_listing_content failed: %s", exc)
        return False
