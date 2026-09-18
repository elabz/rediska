## 1. Schema and settings

- [ ] 1.1 Alembic revision (next free number): `post_fingerprints`, `post_fingerprint_bands`, `copy_clusters`, `copy_cluster_members`, `copy_cluster_suppressions` with indexes on `band_hash`, `external_post_id`, `author_username`, `exact_hash`
- [ ] 1.2 SQLAlchemy models
- [ ] 1.3 Settings `COPY_MIN_CHARS`, `COPY_JACCARD_THRESHOLD`, `COPY_RING_WINDOW_DAYS`, `COPY_SKIP_RING_SUSPECTS` in `config.py`, `.env.example`, and the core/worker/beat compose environment blocks

## 2. Fingerprint core

- [ ] 2.1 `domain/services/post_copy.py`: normalise, shingle, bottom-k sketch, exact hash, Jaccard estimate (pure Python, no new dependency)
- [ ] 2.2 Unit tests with synthetic text: identical, 70% overlap, 20% overlap, short body, boilerplate band cut-off, details-block exclusion
- [ ] 2.3 `fingerprint_post()` get-or-create by `external_post_id`, band rows, repost link for same author
- [ ] 2.4 Candidate lookup + cluster join/create/merge with audit entries
- [ ] 2.5 Classification function + recompute on membership or remote-status change; tests for every branch
- [ ] 2.6 Suppression check for `coincidence`

## 3. Ingest hooks

- [ ] 3.1 Call `fingerprint_post()` in `ScoutWatchService.record_post`, `LeadsService.save_lead`, `profile-items/ingest-browse-posts`, and post-type profile item ingest, after body resolution; failure logs a warning and never fails ingestion
- [ ] 3.2 Ring-suspect skip in `check_author_verdict` (`SKIP_COPY_RING_SUSPECT`), trial exemption, `_should_promote` refusal
- [ ] 3.3 Integration tests: ring skip, returning author analysed, flag off, trial yield count

## 4. API and read models

- [ ] 4.1 `/copy-clusters` list, detail, decision routes with schemas and audit
- [ ] 4.2 Batched `copy` fields on leads list/detail, scout run detail, watch history, needs-review queue
- [ ] 4.3 BFF proxy routes under `apps/web/src/app/api/core/copy-clusters`

## 5. Web

- [ ] 5.1 `CopyBadge` + cluster drawer component
- [ ] 5.2 Mount on lead cards, lead detail, scout history posts, needs-review items, profile page
- [ ] 5.3 Copies tab on `/leads` with filters, decision buttons, empty and error states
- [ ] 5.4 Vitest for badge, drawer, tab

## 6. Backfill and rollout

- [ ] 6.1 `copy.backfill_fingerprints` task (queue `maintenance`, routed by task name, `jobs` idempotency, dry run default, batch audit)
- [ ] 6.2 Routing test passes (`test_task_routing_unit.py`)
- [ ] 6.3 Deploy with skip off, run dry run then live backfill, review top clusters
- [ ] 6.4 Enable `COPY_SKIP_RING_SUSPECTS`
- [ ] 6.5 Update CLAUDE.md (tables, tasks, env) and README
