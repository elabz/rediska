# Design: resolve-external-listing-content

## Context

r/bdsmpersonals posts are now link-only: `selftext` is empty and the post `url` points to an external listing page (`https://weheartbdsm.com/listings/<id>?from=reddit`). `RedditAdapter._map_post` (adapter.py:901) maps `selftext` → `body_text`, so these posts flow through browse, leads, scout watch, and profile items with no text — leaving nothing to display and, critically, nothing for the LLM analysis pipeline to analyze.

Post bodies are persisted in four places, all fed from `ProviderPost.body_text`:
- browse feed responses (`sources.py` route → `BrowseService`)
- `lead_posts.body_text` + mirrored `profile_items.text_content` (`LeadsService.save_lead`)
- `scout_watch_posts.post_body` (`ScoutWatchService.record_post`)
- `profile-items/ingest-browse-posts` batch upsert

Analysis is triggered from two of these paths (auto-analyze on lead save; scout `analyze_and_decide`), so content must be resolved before those triggers fire.

## Goals / Non-Goals

**Goals:**
- Substitute the listing page's About-section text as the post body for supported hosts, stored as if it were the Reddit post's own content.
- **Hard ordering guarantee: resolution completes (or conclusively fails) BEFORE any AI analysis of the post is enqueued or run.** Analysis must never run against the bare link when resolvable content exists.
- Best-effort and polite: never fail ingestion, never hammer the listing host.
- Extensible host registry.

**Non-Goals:**
- Generic scraping, image capture, historical backfill, UI changes, analysis changes (see proposal Non-goals).

## Decisions

1. **Resolve in a domain service, not in the Reddit adapter.**
   New `rediska_core/domain/services/external_listing.py` with `ExternalListingResolver.resolve(url) -> str | None` and `maybe_resolve_post_body(body_text, url) -> str` (returns resolved text when body is empty/link-only and the URL matches a registered host; otherwise returns the original body).
   *Why not inside `_map_post`?* Mapping is pure/sync and used in bulk (a browse page maps ~100 posts); doing network I/O per-post inside the adapter would slow listing endpoints and violate the adapter's mapping-only role. Service-layer hooks let each path choose sync resolution (persistence paths) vs. skip (pure display lists can still resolve lazily if needed).

2. **Hook points and ordering (addresses the "read BEFORE AI analysis" requirement):**
   - `LeadsService.save_lead`: resolve **synchronously before** writing `lead_posts.body_text` and the mirrored `profile_item`, i.e. before the route returns and before the frontend fires the fire-and-forget `analyze` call. The analysis therefore always sees resolved content.
   - Scout watch path: resolve **synchronously before** persisting `post_body`/its profile_item and before `scout.analyze_and_decide` is enqueued. Resolution happens in **two** places by design: `tasks/scout.py` resolves first (it needs the resolved text for its own empty-body skip and for the `analyze_and_decide` payload), and `ScoutWatchService.record_post` resolves **defensively** so any future caller of the service also persists resolved content. The second call is a no-op — `maybe_resolve_post_body` short-circuits once the body is no longer link-only, so no duplicate fetch occurs.
   - `profile-items/ingest-browse-posts`: resolve before upserting `text_content` (batch: only for posts with empty/link-only bodies and registered hosts).
   - Browse feed (`GET /sources/.../posts`): resolve inline for matching posts so cards show content (bounded: only posts whose body is empty and URL matches; cache makes repeat pages cheap).
   - **Defensive re-check in analysis**: `AnalysisService.analyze_lead` / multi-agent context assembly checks whether the lead's stored body is still link-only with a registered host URL; if so it attempts resolution once and persists the result before building agent context. This covers pre-existing rows saved before this change.

3. **Parsing: `httpx` + `beautifulsoup4`.**
   httpx is already a dependency; add `beautifulsoup4` (pure-Python, no lxml needed). weheartbdsm parser: locate the "About" section (heading/section match, fallback to the main listing description block) and extract normalized text. Each registry entry = URL pattern (`weheartbdsm.com/listings/<id>`) + parser callable. Strip tracking params (`?from=reddit`) for canonical fetch/cache key.

4. **Politeness + caching.**
   - Fetch with 10s timeout, identifying User-Agent (reuse `PROVIDER_REDDIT_USER_AGENT`-style config), no retries beyond one, and a Redis-backed per-host rate limit reusing `infrastructure/rate_limiter.py` (modest QPM, e.g. 30).
   - Cache resolved text in Redis keyed by canonical URL (TTL ~7 days) so sync/scout re-encounters of the same post don't re-fetch. Negative results cached briefly (~1h) to avoid hammering broken pages.

5. **Failure semantics.** Any fetch/parse failure → keep the original (link-only) body, log a warning, continue ingestion and analysis. Never raise out of the hook points.

6. **Detection of "link-only" body.** Body qualifies for resolution when `body_text` is None/blank OR consists solely of the same URL as the post's `url` field (Reddit sometimes mirrors the link into selftext).

## Risks / Trade-offs

- [Listing site changes markup] → parser returns None, posts fall back to link-only bodies (status quo ante); parser is isolated per-host and unit-tested against saved HTML fixtures so fixes are one-file.
- [Synchronous fetch adds latency to save-lead / scout runs] → single fetch with 10s cap + cache; scout runs are background tasks where latency is acceptable; save-lead adds at most one HTTP round-trip.
- [Browse feed latency if many link-only posts on one page] → bound inline resolution (e.g. first N unresolved per request, rest resolve on save) — decided at implementation; cache amortizes subsequent pages.
- [External site sees our traffic] → retrieval-only, generic UA, rate-limited; consistent with existing outbound Reddit traffic and the local-only policy (nothing stored is transmitted out).
- [Stored body no longer matches Reddit's view of the post] → intended per requirements ("store as if it's the content of the corresponding Reddit post"); original URL preserved in `post_url`/raw_data.

## Migration Plan

No schema migration. Deploy core+worker together (worker imports core services). Rollback = revert; already-resolved bodies remain (harmless). Pre-existing link-only rows get resolved lazily by the analysis-path re-check, or on reanalyze.

## Open Questions

- Exact DOM selector for the About section (to be confirmed against a live listing page during implementation; parser fixtures captured then).
- Whether browse-feed inline resolution needs a per-request bound (measure during implementation).
