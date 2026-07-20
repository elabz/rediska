# Proposal: resolve-external-listing-content

## Why

Posts in r/bdsmpersonals (and potentially other subreddits) no longer carry their content in the Reddit post body: the post is now a link-only post pointing to an external listing page such as `https://weheartbdsm.com/listings/8980?from=reddit`. Since `RedditAdapter._map_post` takes `body_text` from `selftext`, these posts arrive with an empty body — browse cards show nothing, saved leads have no text, and the LLM analysis pipeline (interests/character summaries, multi-agent analysis) has no content to work from.

## What Changes

- Introduce an **external listing content resolver**: when an ingested post has an empty/link-only body and its URL matches a supported listing host (initially `weheartbdsm.com/listings/<id>`), the system fetches the listing page, extracts the text of its **About** section, and uses that text as the post's body — stored exactly as if it were the content of the corresponding Reddit post.
- Resolution applies everywhere post content is ingested/persisted: browse feed results, lead saving (`lead_posts.body_text` + the mirrored `profile_items.text_content`), scout watch post recording (`scout_watch_posts.post_body`), and single-post fetches.
- Resolution is best-effort: on fetch/parse failure the post is kept with its original (link-only) body and ingestion never fails.
- Resolved content is fetched politely (timeout, identifying UA, per-host rate limit) and cached/deduped so a listing is not re-fetched on every sync or upsert.
- Supported hosts live in a small registry so future listing sites can be added without touching ingestion code.
- New Python dependency for HTML parsing (`beautifulsoup4`).

## Capabilities

### New Capabilities
- `external-listing-resolution`: fetching and parsing supported external listing pages (starting with weheartbdsm.com) and substituting the extracted About text as the post body across all post-ingestion paths.

### Modified Capabilities

_None — browse-discovery, leads, and scout-watch requirements are unchanged; they receive already-resolved post bodies. The new capability spec defines where resolution hooks in._

## Impact

- **Core service**:
  - New domain service `rediska_core/domain/services/external_listing.py` (resolver + host registry + parser).
  - Hook points: `BrowseService` (browse feed / `sources.py` route), `LeadsService.save_lead`, `ScoutWatchService.record_post`, `ingest.fetch_post` path, `profile-items/ingest-browse-posts`.
  - `services/core/pyproject.toml`: add `beautifulsoup4`.
- **Worker**: browse/scout/ingest Celery tasks transparently benefit; no new tasks required (resolution happens in the domain services they call).
- **Data**: no schema changes — resolved text is stored in existing columns (`lead_posts.body_text`, `scout_watch_posts.post_body`, `profile_items.text_content`). Original listing URL remains in `post_url`/raw data.
- **Network**: adds outbound HTTPS fetches to listing hosts (retrieval only — consistent with the local-only policy; no stored content is transmitted out).
- **UI**: no changes; pages simply start showing real content for link-only posts.

## Non-goals

- No generic web scraper: only explicitly registered listing hosts are resolved.
- No fetching of images/attachments from listing pages (text of the About section only).
- No re-resolution/refresh of already-stored bodies (a listing is resolved when the post is ingested; historical backfill is out of scope, though the resolver may be invoked manually later).
- No change to analysis pipelines — they consume post bodies as before.
- No content filtering of any kind (per research-content-policy).
