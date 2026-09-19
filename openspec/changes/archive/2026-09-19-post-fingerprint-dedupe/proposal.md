## Why

Reviewing leads exposed that different accounts post the same text. A scan of the 25,705 stored post bodies (2026-09-18) found 510 clusters of copied text shared by two or more authors, covering 1,551 of 6,760 authors (23%), the largest spanning 25 accounts. Some are scam rings posting from several accounts; most are one person who deleted an account and came back, whose earlier analysis and verdict we already hold but never see. Today nothing connects these posts: `content_fingerprint()` only compares an author with their own past posts, and the 3-day scout history cleanup deletes the text before a copy can ever be noticed.

## What Changes

- **A fingerprint for every post seen.** Each post that reaches the system (scout runs including posts skipped before analysis, source-discovery trials, browse ingest, saved leads, profile items of type post) gets a row holding author, post time, an exact hash of the normalised text, and a 64-value MinHash sketch over 5-word shingles. No post text is stored in the row, so it survives history cleanup at about 0.5 KB per post.
- **Copy lookup at ingest, before any LLM call.** A new post is compared against all stored fingerprints in a few milliseconds (banded sketch lookup in MySQL, exact Jaccard estimate on candidates). Matches by a *different* author at estimated Jaccard ≥ 0.5 join a copy cluster.
- **Copy clusters with a classification.** Each cluster carries its member posts, distinct authors, and a computed kind: `returning_author` (the earlier account is deleted/suspended or has been silent, and the gap is long), `ring_suspect` (two or more live accounts posting the copy within `COPY_RING_WINDOW_DAYS`, default 7, or three or more authors in total), or `unclassified`. Classification is plain Python over stored fields; it never calls an LLM.
- **Prior knowledge is surfaced, not acted on.** Lead detail, scout history posts, the needs-review queue and the profile page show a copy badge with the cluster: who else posted it, when, their account state, and links to earlier analyses, lead statuses and human verdicts. For `returning_author` the earlier verdict is shown as context; it does not skip analysis, because verdicts are content-scoped to an author and this is a new author.
- **Ring suspects do not auto-promote.** A scout post whose cluster is `ring_suspect` is analysed only if the watch opts in; by default it is recorded as `skipped` with reason `copy_ring_suspect`, stays visible in history, and is never auto-promoted. The human can still promote it manually. Ring suspects feed the ban-suggestion queue defined in the `contact-ban-list` change when that change is present.
- **Backfill.** A one-off task fingerprints the ~25.7k stored post bodies and builds clusters (measured: 8 s of CPU for the whole corpus).
- **Cluster review page.** `/leads` gains a "Copies" tab listing clusters by size and recency with a human decision per cluster: `confirmed_ring`, `same_person`, `coincidence` (template or quoted text). `coincidence` dissolves the cluster and suppresses it from re-forming.

## Non-goals

- No embeddings or semantic matching here. Measured on this corpus, 93% of cross-author pairs at cosine ≥ 0.95 were already caught by word overlap; the semantic second pass belongs to `semantic-similarity-search`.
- No automatic ban and no automatic merge of accounts. Clusters inform the human; banning is the `contact-ban-list` change.
- No image matching (shared photos). The unused `duplicate_detection.py` is left to the `remove-dead-weight` decision.
- No content filtering: fingerprints are computed over verbatim text and nothing is redacted or hidden from the user.
- No provider calls: account state comes from fields already stored.

## Capabilities

### New Capabilities
- `post-copy-detection`: post fingerprints, copy lookup, copy clusters and their classification, human cluster decisions, backfill, API and UI surfaces.

### Modified Capabilities
- `scout-watch`: every recorded post is fingerprinted before analysis; ring-suspect copies are skipped with a stored reason and never auto-promoted; fingerprints are exempt from history cleanup.
- `leads`: lead detail and lead list expose the copy cluster and prior analyses of other authors of the same text.

## Impact

- **DB** (one Alembic revision): `post_fingerprints`, `post_fingerprint_bands`, `copy_clusters`, `copy_cluster_members`, `copy_cluster_suppressions`.
- **Core**: new `domain/services/post_copy.py`; hooks in `ScoutWatchService.record_post`, `LeadsService.save_lead`, `profile-items/ingest-browse-posts`, profile item ingest; `check_author_verdict` gains the ring-suspect skip; new `/copy-clusters` routes; read models for leads, scout posts, needs-review and profile carry `copy` fields.
- **Worker**: `copy.backfill_fingerprints` (queue `maintenance`, `jobs` idempotency, dry run first); `maintenance.cleanup_scout_watch_history` untouched because fingerprints live in their own tables.
- **Web**: copy badge component, cluster drawer, Copies tab, BFF proxies under `/api/core/copy-clusters`.
- **Settings**: `COPY_MIN_CHARS` (200), `COPY_JACCARD_THRESHOLD` (0.5), `COPY_RING_WINDOW_DAYS` (7), `COPY_SKIP_RING_SUSPECTS` (true) — each added to `.env.example` **and** the compose environment blocks.
- **Storage/compute**: ~0.5 GB per million posts; at the full firehose (~2,300 posts/day) that is ~0.4 GB per year. No GPU, no new dependency.
