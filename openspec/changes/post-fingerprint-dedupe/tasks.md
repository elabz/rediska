## 1. Schema and settings

- [x] 1.1 Alembic revision (next free number): `post_fingerprints`, `post_fingerprint_bands`, `copy_clusters`, `copy_cluster_members`, `copy_cluster_suppressions` with indexes on `band_hash`, `external_post_id`, `author_username`, `exact_hash`
- [x] 1.2 SQLAlchemy models
- [x] 1.3 Settings `COPY_MIN_CHARS`, `COPY_JACCARD_THRESHOLD`, `COPY_RING_WINDOW_DAYS`, `COPY_SKIP_RING_SUSPECTS` in `config.py`, `.env.example`, and the core/worker/beat compose environment blocks
- [x] 1.4 `copy_cluster_members.ban_suggestion_dismissed_at` (nullable DATETIME), and check `BanListService.suggestions()` / `cluster_usernames()` / `dismiss_suggestion()` (contact-ban-list) against the real column names — they assume `copy_clusters(kind, decision)`, `copy_cluster_members(cluster_id, fingerprint_id)`, `post_fingerprints(provider_id, author_username, posted_at, first_seen_at)`; add a test with the tables present

## 2. Fingerprint core

- [x] 2.1 `domain/services/post_copy.py`: normalise, shingle, bottom-k sketch, exact hash, Jaccard estimate (pure Python, no new dependency)
- [x] 2.2 Unit tests with synthetic text: identical, 70% overlap, 20% overlap, short body, boilerplate band cut-off, details-block exclusion
- [x] 2.3 `fingerprint_post()` get-or-create by `external_post_id`, band rows, repost link for same author
- [x] 2.4 Candidate lookup + cluster join/create/merge with audit entries
- [x] 2.5 Classification function + recompute on membership or remote-status change; tests for every branch
- [x] 2.6 Suppression check for `coincidence`

## 3. Ingest hooks

- [x] 3.1 Call `fingerprint_post()` in `ScoutWatchService.record_post`, `LeadsService.save_lead`, `profile-items/ingest-browse-posts`, and post-type profile item ingest, after body resolution; failure logs a warning and never fails ingestion
- [x] 3.2 Ring-suspect skip in `check_author_verdict` (`SKIP_COPY_RING_SUSPECT`), trial exemption, `_should_promote` refusal
- [x] 3.3 Integration tests: ring skip, returning author analysed, flag off, trial yield count

## 4. API and read models

- [x] 4.1 `/copy-clusters` list, detail, decision routes with schemas and audit
- [x] 4.2 Batched `copy` fields on leads list/detail, scout run detail, watch history, needs-review queue
- [x] 4.3 BFF proxy routes under `apps/web/src/app/api/core/copy-clusters`

## 5. Web

- [x] 5.1 `CopyBadge` + cluster drawer component
- [x] 5.2 Mount on lead cards, lead detail, scout history posts, needs-review items, profile page
- [x] 5.3 Copies tab on `/leads` with filters, decision buttons, empty and error states
- [x] 5.4 Vitest for badge, drawer, tab
- [x] 5.5 Mount `BanControl` (from `contact-ban-list`) per author in the cluster drawer, and a bulk "Ban cluster" action via `POST /ban-list/bulk {cluster_id}`

## 6. Backfill and rollout

- [x] 6.1 `copy.backfill_fingerprints` task (queue `maintenance`, routed by task name, `jobs` idempotency, dry run default, batch audit)
- [x] 6.2 Routing test passes (`test_task_routing_unit.py`)
- [x] 6.3 Deploy with skip off, run dry run then live backfill (45,038 fingerprints, 509 clusters); review replaced by automatic handling (7.x)
- [x] 6.4 Enable `COPY_SKIP_RING_SUSPECTS`
- [x] 6.5 Update CLAUDE.md (tables, tasks, env) and README

## 7. Automatic spam-ring handling

- [x] 7.1 Migration 023: `copy_clusters.avg_char_len`, `copy_clusters.handled` (+ index); `is_handled()` / `refresh_handled()` recomputed with the kind and on decisions
- [x] 7.2 Settings `COPY_RING_MIN_AUTHORS` (3), `COPY_RING_MIN_CHARS` (400) in config, `.env.example`, compose core/worker/beat
- [x] 7.3 Scout skip uses the handled flag; any ring still never auto-promotes
- [x] 7.4 `GET /leads` and the needs-review queue hide handled rings (`include_copies=true`); `/copy-clusters?handled=`; `copy.handled` on read models
- [x] 7.5 Web: "Show leads from spam rings" toggle, Copies tab defaults to not-handled, handled marker on badge / row / drawer
- [x] 7.6 Tests: predicate branches, recompute, decisions, hidden lists, skip thresholds
- [x] 7.7 Deploy, recompute all clusters, report handled counts
