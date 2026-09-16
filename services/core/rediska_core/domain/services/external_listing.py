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
from dataclasses import dataclass, field
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


@dataclass
class ListingData:
    """Structured fields extracted from a listing page, plus the free-text body.

    Everything here is shown to the analysis agents verbatim; nothing is
    filtered or redacted (see research-content-policy).
    """

    body: str
    title: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    online_only: Optional[bool] = None
    meet_type: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    position: Optional[str] = None
    seeking: Optional[str] = None
    seeking_position: Optional[str] = None
    age_min_sought: Optional[int] = None
    age_max_sought: Optional[int] = None
    is_couple: Optional[bool] = None
    kinks: list[tuple[str, str]] = field(default_factory=list)  # (kink, level)

    def location_line(self) -> Optional[str]:
        place = ", ".join(p for p in (self.city, self.state) if p)
        if not place and self.country:
            place = self.country
        elif place and self.country and self.country.lower() not in place.lower():
            place = f"{place}, {self.country}"
        mode = None
        if self.online_only:
            mode = "online only"
        elif self.meet_type:
            mode = self.meet_type.replace("_", " ")
        if place and mode:
            return f"{place} ({mode})"
        return place or (f"({mode})" if mode else None)

    def details_block(self) -> str:
        """Compact, human-readable facts header placed ahead of the body text."""
        lines = ["[Listing details from weheartbdsm.com]"]
        loc = self.location_line()
        if loc:
            lines.append(f"Location: {loc}")
        who = [f"Age: {self.age}" if self.age is not None else None,
               f"Gender: {self.gender}" if self.gender else None,
               f"Position: {self.position}" if self.position else None,
               "Posting as a couple" if self.is_couple else None]
        who = [w for w in who if w]
        if who:
            lines.append(" | ".join(who))
        seek = []
        if self.seeking:
            seek.append(f"Seeking: {self.seeking}")
        if self.seeking_position:
            seek.append(f"Seeking position: {self.seeking_position.replace(',', ', ')}")
        if self.age_min_sought is not None or self.age_max_sought is not None:
            lo = self.age_min_sought if self.age_min_sought is not None else "?"
            hi = self.age_max_sought if self.age_max_sought is not None else "no max"
            seek.append(f"Sought age range: {lo}-{hi}")
        if seek:
            lines.append(" | ".join(seek))
        if self.kinks:
            lines.append("Kinks: " + ", ".join(
                f"{k} ({lvl})" if lvl else k for k, lvl in self.kinks))
        return "\n".join(lines)

    def as_text(self) -> str:
        """Details block + body, the string stored as the post body."""
        header = self.details_block()
        if header.count("\n") == 0:  # nothing but the banner line
            return self.body
        return f"{header}\n\n{self.body}" if self.body else header


def _opt_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _opt_str(v) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() else None


def parse_weheartbdsm_structured(html: str) -> Optional[ListingData]:
    """Extract structured listing data from a weheartbdsm.com listing page.

    The page is an Inertia.js app: the full listing lives in the JSON
    `data-page` attribute at props.listing (body plus city/state/meet_type/
    age/gender/position/seeking/age range/kinks). A truncated fallback is
    available in the JSON-LD Article block's description (body only).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find(attrs={"data-page": True})
    if tag is not None:
        try:
            page = json.loads(tag["data-page"])
            listing = page.get("props", {}).get("listing") or {}
            body = listing.get("body")
            if isinstance(body, str) and body.strip():
                user = listing.get("user") or {}
                kinks = []
                for k in listing.get("kinks") or []:
                    if isinstance(k, dict) and k.get("kink"):
                        kinks.append((str(k["kink"]), str(k.get("level") or "")))
                return ListingData(
                    body=_normalize_text(body),
                    title=_opt_str(listing.get("title")),
                    city=_opt_str(listing.get("city")),
                    state=_opt_str(listing.get("state")),
                    country=_opt_str(user.get("location")),
                    online_only=bool(listing["online_only"]) if listing.get("online_only") is not None else None,
                    meet_type=_opt_str(listing.get("meet_type")),
                    age=_opt_int(user.get("age")),
                    gender=_opt_str(user.get("gender")),
                    position=_opt_str(listing.get("position") or user.get("position")),
                    seeking=_opt_str(listing.get("seeking")),
                    seeking_position=_opt_str(listing.get("seeking_position")),
                    age_min_sought=_opt_int(listing.get("age_min_sought")),
                    age_max_sought=_opt_int(listing.get("age_max_sought")),
                    is_couple=bool(listing["is_couple"]) if listing.get("is_couple") is not None else None,
                    kinks=kinks,
                )
        except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
            logger.warning("weheartbdsm: failed to parse data-page JSON")

    # Fallback: JSON-LD Article description (may be truncated; body only)
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Article":
            description = data.get("description")
            if isinstance(description, str) and description.strip():
                return ListingData(body=_normalize_text(description))

    return None


def parse_weheartbdsm(html: str) -> Optional[str]:
    """Listing text as stored for analysis: details block + About/body text."""
    data = parse_weheartbdsm_structured(html)
    return data.as_text() if data else None


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
