## 1. Data model

- [x] 1.1 Alembic migration `020_add_source_discovery`: `source_candidates` (kind, provider_id, name/host, origin mined|manual, evidence_json, lift, status, snoozed_until, location_info_json, watch_id, timestamps; unique on provider+kind+name), `source_trials` (candidate_id, watch_id, status, sample_size, progress, yield_json, job link, timestamps), `scout_watches.is_trial` default false
- [x] 1.2 SQLAlchemy models and Pydantic schemas for candidates, trials, yield report, and `ProviderLocation`
- [x] 1.3 Upgrade and downgrade tested against a throwaway MySQL container

## 2. Provider contract

- [x] 2.1 Add `ProviderLocation` DTO plus `search_locations` and `get_location_info` to `providers/base.py` (default `NotImplementedError`)
- [x] 2.2 Implement both in `providers/reddit/adapter.py` through the existing rate limiter; return `None` for private, banned, or missing communities; no NSFW filtering
- [x] 2.3 Unit tests with synthetic API payloads: search mapping, unavailable location, rate-limit pacing

## 3. Mining

- [x] 3.1 `source_discovery.py`: `is_qualified_author()` (suitable verdict, contacted/engaged, effective human agree; excludes do-not-contact and soft-deleted leads)
- [x] 3.2 Location lift computation: two grouped queries over `profile_items`, add-one smoothing, evidence floor, trailing window, exclusion of watched locations
- [x] 3.3 Outbound host tally from link-only scout/browse posts and qualified authors' items, tracking params stripped, registry hosts excluded, up to five example URLs
- [x] 3.4 Upsert logic: update evidence in place, never resurrect `dismissed`, un-snooze when `snoozed_until` passes
- [x] 3.5 Worker task `discovery.mine_candidates` on the `scout` queue with `jobs` idempotency (one run per day) and a retry policy; daily beat entry; route pattern plus `test_task_routing_unit.py` rows
- [x] 3.6 Unit tests on synthetic data: over-represented community, thin evidence, popular community with lift near 1, watched exclusion, dismissed stays dismissed, registered host excluded, no HTTP request issued to any host

## 4. Candidate API

- [x] 4.1 Routes under `/source-candidates`: list (filters, lift sort, cursor), dismiss, restore, snooze, accept, manual add, search; static paths declared before `/{id}`
- [x] 4.2 Lazy location-info fetch and cache on first display
- [x] 4.3 `audit_log` on dismiss, restore, snooze, accept, manual add, trial start, trial cancel
- [x] 4.4 Integration tests: lifecycle transitions, accept creates exactly one watch, search annotates watched/candidate/dismissed, every mutation audited

## 5. Trials

- [x] 5.1 Trial creation: hidden `is_trial` watch, `source_trials` row, conflict when another trial is running, rejection for `external_host` candidates
- [x] 5.2 Worker task `discovery.run_trial`: bounded sample fetch, external-listing resolution before `record_post`, per-post pipeline, cancel check between posts, `jobs` ledger, `max_retries=0`
- [x] 5.3 Guard in `scout.analyze_and_decide` so posts of an `is_trial` watch are never auto-promoted; manual add-to-leads still works
- [x] 5.4 Yield report aggregation (posts fetched, skipped empty, link-only resolved, per-recommendation counts, top failing gate, median post age); candidate becomes `trialled`
- [x] 5.5 Shared `is_trial = false` filter applied to: watch list, `run_all_watches`, needs-review queue, calibration report, evaluation queue sampling
- [x] 5.6 History cleanup exemption for unresolved trials; detach on dismiss; in-place conversion on accept so seen posts are not re-analysed
- [x] 5.7 Tests: yield report numbers, high-scoring trial post not promoted, second trial refused, cancel mid-run, trial watch invisible on each filtered surface, accept converts in place

## 6. Watch yield

- [x] 6.1 Add trailing-30-day yield fields to the scout-watch read model using batched aggregation (no per-watch query loop)
- [x] 6.2 Tests for the low-yield watch scenario and for query count staying constant as watches grow

## 7. Web

- [x] 7.1 BFF proxies under `apps/web/src/app/api/core/source-candidates/`
- [x] 7.2 Discover tab on `/settings/scout-watches`: candidate list with evidence, location info, trial yield, actions (trial, cancel, create watch, snooze, dismiss, restore), keyword search with add
- [x] 7.3 Create-watch dialog pre-filled from the candidate, reusing the existing watch form
- [x] 7.4 Trial progress polling; empty, loading, and error states; yield column on the watch list
- [x] 7.5 Vitest coverage for the tab states and actions; `npm run lint` clean

## 9. Follow-ups from the first real candidate list

- [x] 9.1 Evidence-weighted lift (shrink toward the base rate by 10 pseudo-authors) so 3-of-3 communities stop topping the list
- [x] 9.2 Provider returns community rules with location info; `contact_restriction()` flags communities that forbid approaching posters, tuned on real rules; `hide_restricted` filter (UI default on)
- [x] 9.3 Hide private/banned/missing locations from all views except `status=all`; refetch info that predates the rules check
- [x] 9.4 "Preview search" opens Browse in a new tab with the watches' longest query; Browse reads `location`/`q`/`sort`/`t` URL params; create-watch form pre-filled with the query
- [x] 9.5 Name filter (`q`) on the candidate list; curated regional (PA/NJ/DE/MD/NYC) personals subreddits added as manual candidates

## 8. Config, docs, rollout

- [x] 8.1 `DISCOVERY_MIN_QUALIFIED_AUTHORS`, `DISCOVERY_TRIAL_SAMPLE`, `DISCOVERY_WINDOW_DAYS` in `config.py`, `.env.example`, and the `docker-compose.yml` environment blocks for core and worker
- [x] 8.2 Update CLAUDE.md (architecture section, tables, Celery tasks, env vars, pages) and README
- [x] 8.3 Full core and worker suites green in Docker
- [x] 8.4 Deploy mining plus read-only list first; user reviews the first candidate list for sanity before trials are enabled
- [x] 8.5 Sync delta specs into `openspec/specs/`, diff the synced specs, archive
