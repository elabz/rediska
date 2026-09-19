## Context

Posts enter through four paths (`ScoutWatchService.record_post`, `LeadsService.save_lead`, `profile-items/ingest-browse-posts`, profile item ingest), all of which already call `maybe_resolve_post_body` first, so the text available at that point is the real body. `scout_watch.content_fingerprint()` hashes title+body but is only compared within one author. Scout history older than 3 days is deleted (analysed posts are detached, not deleted), so any detector that needs the text later will miss most copies.

Measured on 2026-09-18 over 25,705 bodies ≥ 200 chars: 5-word shingles, bottom-k sketch, pure Python, 8 s end to end. Cross-author pairs at Jaccard ≥ 0.5: 7,408; gap < 1 day ≈ 7%, 1–7 days ≈ 15%, 7–30 days ≈ 38%, > 30 days ≈ 40%. Timestamps mix post time and first-seen time, so gaps are approximate.

Constraints: no LLM or provider calls in the detection path; verbatim content; verdicts are content-scoped per author; `needs_review` is for humans; every mutation audited; settings must be wired through compose.

## Goals / Non-Goals

**Goals:** detect identical and lightly edited copies across authors at ingest; keep detection alive after history cleanup; tell returning authors from rings; show the human what we already know; keep cost negligible at millions of posts.

**Non-Goals:** semantic rewrites, image reuse, automatic bans, account merging, any filtering.

## Decisions

**1. MinHash sketch in MySQL, not Elasticsearch, not embeddings.**
Normalise (lowercase, `[a-z0-9']+` tokens), shingle 5 words, hash each shingle once (64-bit from blake2b), keep the 64 smallest values (bottom-k). Jaccard is estimated from two sketches. Candidate lookup uses the 8 smallest values as band keys in `post_fingerprint_bands(band_hash, fingerprint_id)` with an index on `band_hash`; two posts sharing ≥ 50% of shingles share at least one of the 8 smallest with probability > 99%. *Alternatives:* ES `more_like_this` (needs the text indexed forever, fuzzy scores, slower); embeddings (4–16 GB per million, GPU time, 7% extra recall, false positives below cosine 0.92); SimHash (weak on short edits of long text). Bands with more than 200 members are treated as boilerplate and ignored for candidate generation.

**2. Fingerprint row holds no text.**
`post_fingerprints(id, provider_id, external_post_id UNIQUE, author_username, account_id NULL, location, posted_at, first_seen_at, char_len, exact_hash BINARY(16), sketch VARBINARY(512), source ENUM(scout, trial, browse, lead, profile_item))`. Text stays where it already lives. Posts under `COPY_MIN_CHARS` get an exact hash only and no bands, since short posts collide on stock phrases. Title is excluded from the sketch (titles are tag soup: `F4M #newyork`), included in nothing.

**3. External-listing details block is excluded.**
The structured details block prepended for weheartbdsm listings is boilerplate-shaped. The fingerprint is computed on the resolved About text before the block is prepended.

**4. Clusters are maintained incrementally with union semantics.**
A new post matching members of one cluster joins it; matching two clusters merges them (smaller into larger, audit entry); matching an unclustered post creates a cluster. Same-author matches are recorded on the fingerprint (`repost_of_id`) but never create a cluster: reposting your own ad is normal and distinct-target-authors/day ≈ posts/day already.

**5. Classification is recomputed on every membership change, from stored fields only.**
`ring_suspect` when ≥ 2 distinct authors whose `external_accounts.remote_status` is not deleted/suspended posted within `COPY_RING_WINDOW_DAYS` of each other, or when distinct authors ≥ 3. `returning_author` when exactly 2 authors, gap > window, and the earlier account is deleted/suspended or has no item newer than the later account's first item. Else `unclassified`. A human decision (`confirmed_ring`, `same_person`, `coincidence`) overrides and is sticky. *Alternative:* an LLM judge — rejected, the signal is temporal and structural, not linguistic.

**6. Ring-suspect skip sits in `check_author_verdict`, after do-not-contact.**
It reuses the existing `skipped` + stored-reason mechanism, so the post stays visible in history and costs no profile fetch or inference. `returning_author` never skips: the new account may have new profile content and the analysis is cheap relative to the value. Trials ignore the skip so yield reports reflect the raw source, but count ring suspects in the yield report.

**6b. Spam rings are handled automatically, by skip and hide only (added 2026-09-19).**
The user judged ring suspects not worth reviewing one by one. A cluster is `handled` when it is a `confirmed_ring`, or an undecided `ring_suspect` with ≥ `COPY_RING_MIN_AUTHORS` (3) authors whose posts average ≥ `COPY_RING_MIN_CHARS` (400) characters. The flag and `avg_char_len` are stored on `copy_clusters` (migration 023) and recomputed with the kind. Handled clusters drive the scout skip and are excluded from `GET /leads` and the needs-review queue (`include_copies=true` shows them). Two-author clusters (145 of 325 at backfill) and short posts (possible posting templates, e.g. a 17-account 222-char cluster) stay for the human; any ring still never auto-promotes. *Alternative rejected:* automatic bans — they would block the authors' other posts and messaging on timing evidence alone, and break "bans only by user action".

**7. `coincidence` needs a suppression list.**
Dissolving a cluster stores its members' `exact_hash`/sketch in `copy_cluster_suppressions`; a future match whose best partner is suppressed does not form a cluster. This handles subreddit templates and quoted song lyrics.

**8. Read models are batched.**
Lead list, needs-review and scout history attach `copy` fields with one query per page (`fingerprint by external_post_id IN (...)` → cluster summary), following the batched-query rule established for `build_lead_responses`.

## Risks / Trade-offs

- [Templates and rules text create false clusters] → oversize-band cut-off, `COPY_MIN_CHARS`, `coincidence` decision with suppression.
- [A popular ad copied by an innocent third party is labelled a ring] → label is `ring_suspect`, shown with evidence; only a human confirms; manual promotion still works.
- [Skipping ring suspects hides a real person] → skip is visible in history with reason, configurable off, and needs-review never loses posts silently because skipped posts were never going to reach it.
- [Timestamps mix sources] → store both `posted_at` and `first_seen_at`; gaps use `posted_at` when present.
- [Username recycling across rows with NULL account_id] → author identity for clustering is lower-cased username; `account_id` is filled when known.
- [Backfill on live DB] → read-only pass, batched inserts, dry run reports counts first.

## Migration Plan

1. Alembic revision creates the five tables (incl. suppressions). No existing table changes.
2. Deploy with `COPY_SKIP_RING_SUSPECTS=false`; ingest hooks start writing fingerprints.
3. Run `copy.backfill_fingerprints` dry run, then live; review the Copies tab.
4. After reviewing the top clusters, set `COPY_SKIP_RING_SUSPECTS=true`.
Rollback: disable the hooks with the flag; tables are additive and can be dropped.

## Open Questions

- Should `returning_author` with an earlier `ignored` lead lower the new lead's priority one tier? Proposed: no, show only; revisit after a month of data.
- Should comments be fingerprinted? Proposed: no (avg 108 chars).
