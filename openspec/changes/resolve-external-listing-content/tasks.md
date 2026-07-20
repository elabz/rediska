# Tasks: resolve-external-listing-content

## 1. Resolver service

- [x] 1.1 Add `beautifulsoup4` to `services/core/pyproject.toml` dependencies
- [x] 1.2 Capture a saved-HTML fixture of a weheartbdsm.com listing page (test fixture, confirm About-section DOM structure) — the operator should provide/download the sample page; do not browse live rediska
- [x] 1.3 Create `rediska_core/domain/services/external_listing.py`: host registry (URL pattern → parser), canonical URL normalization (strip tracking params), `is_link_only_body()` helper, `maybe_resolve_post_body(body_text, url)`
- [x] 1.4 Implement weheartbdsm parser: fetch via httpx (10s timeout, identifying UA), extract About-section text with BeautifulSoup, normalize whitespace
- [x] 1.5 Add Redis caching (resolved text ~7d TTL, negative cache ~1h) and per-host rate limiting via `infrastructure/rate_limiter.py`
- [x] 1.6 Unit tests: link-only detection, URL matching/canonicalization, parser against fixture, failure fallback (timeout, 404, missing About), cache hit skips fetch

## 2. Ingestion hook points (resolution BEFORE analysis)

- [x] 2.1 `LeadsService.save_lead`: resolve synchronously before persisting `lead_posts.body_text` and the mirrored `profile_item` (so the auto-analyze call always sees resolved content); tests
- [x] 2.2 `ScoutWatchService.record_post`: resolve synchronously before persisting `post_body`/profile_item and before `scout.analyze_and_decide` is enqueued; tests
- [x] 2.3 `profile-items/ingest-browse-posts`: resolve qualifying posts during batch upsert; tests
- [x] 2.4 Browse feed (`BrowseService` / `sources.py`): resolve qualifying posts inline (bounded per request if needed per design open question); tests
- [x] 2.5 Analysis defensive re-check: in `AnalysisService.analyze_lead` (and multi-agent context assembly), if stored lead body is still link-only with a registered host URL, resolve once and persist before building agent context; tests

## 3. Verification & docs

- [x] 3.1 Integration test: link-only post → save lead → assert `lead_posts.body_text`, `profile_items.text_content` contain resolved text and analysis context receives it (mocked HTTP)
- [x] 3.2 Integration test: scout watch run with link-only post → assert `post_body` resolved before analyze task enqueue (mocked HTTP)
- [x] 3.3 Run `pytest` (core + worker) and `npm run lint` — all green
- [ ] 3.4 Update `openspec/specs/external-listing-resolution/spec.md` via archive flow when done; note the new dependency in CLAUDE.md tech notes if needed
