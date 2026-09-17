# Proposal: dedupe-leads-by-author

## Why

The lead-quality review found that ~33% of scout-watch leads are duplicates of the same person: 2,754 leads map to only 1,858 distinct authors. Deduplication today is per-watch by `external_post_id` only (`ScoutWatchService.is_post_seen`), so an author cross-posting to several watched subreddits produces one lead per post. Worse, prior verdicts are not honored: authors the user already ignored or contacted are re-analyzed (wasting LLM cycles) and re-surfaced as fresh leads, bloating the funnel and lowering perceived lead quality.

## What Changes

- **One active lead per author**: lead creation (scout auto-promotion, manual add-to-leads, and `POST /leads/save`) attaches a new post to the author's existing lead instead of creating a duplicate `lead_posts` row. The post itself is already preserved as a `profile_item`; the existing lead's `updated_at` and latest-analysis linkage are refreshed.
- **Prior verdicts short-circuit the pipeline**: before the expensive profile-fetch/summarize/analyze pipeline runs in `scout.analyze_and_decide`, authors whose existing lead is `ignored`, whose account is already contacted/engaged, or who are on `do_not_contact` are skipped, with the scout post marked `skipped` and a stored reason. This also cuts LLM load.
- **Manual save path**: `LeadsService.save_lead` (which currently upserts by `(provider_id, external_post_id)` only) returns/updates the author's existing lead when one exists, so the UI surfaces the existing lead rather than silently creating a sibling.
- **One-time cleanup**: a maintenance task (dry-run by default) merges the existing ~900 duplicate-author leads — newest post wins as the lead's primary post, analysis history is preserved.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `leads`: saving a post by an author who already has an active lead updates/returns that lead instead of creating a duplicate; at most one active lead per (provider, author account).
- `scout-watch`: dedupe becomes author-aware across watches; prior verdicts (ignored lead, contacted/engaged account, do-not-contact) skip analysis before the pipeline runs; auto-promotion attaches to an existing lead when one exists.

## Impact

- **Core service**: `LeadsService.save_lead` (author-level lookup + attach semantics), `ScoutWatchService` (pre-analysis verdict check helper, `save_lead_from_watch` attach path), leads list/detail schemas unchanged (badge counts may reflect merged posts).
- **Worker**: `scout.analyze_and_decide` gains an early skip gate before profile fetch; `scout.run_single_watch` unchanged; new one-time maintenance task for merging historical duplicates.
- **Data**: no schema changes required (existing `lead_posts`, `scout_watch_posts.analysis_status='skipped'` + reasoning fields suffice); cleanup task mutates existing rows only.
- **UI**: no redesign — Leads list simply shows fewer, deduplicated entries; scout history shows skip reasons already supported by the `skipped` state.
- **Audit**: skips, attaches, and merges write audit log entries per project invariants.

## Non-goals

- No changes to analysis quality, decision gates, thresholds, or prompts (covered by separate changes from the same review).
- No UI redesign beyond existing badges/counters reflecting deduplicated data.
- No cross-provider or fuzzy identity resolution — author identity is the exact `(provider_id, external_username)` account match; integrating the existing `duplicate_detection` service is future work.
- No automatic deletion of duplicate leads without an explicit operator-triggered run of the cleanup task (dry-run is the default).
