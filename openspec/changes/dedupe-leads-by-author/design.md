# Design: dedupe-leads-by-author

## Context

Lead creation happens in three places, none author-aware:

1. `LeadsService.save_lead` (core) — upserts `lead_posts` by `(provider_id, external_post_id)`; called by `POST /leads/save` and by `ScoutWatchService.save_lead_from_watch`.
2. `scout.analyze_and_decide` (worker) — on `suitable` + confidence ≥ `min_confidence`, calls `save_lead_from_watch`.
3. `POST /scout-watches/.../add-post-to-leads` — manual promotion.

Scout dedupe (`is_post_seen`) is per-watch by `external_post_id`, so cross-posting authors generate one lead per post per subreddit (2,754 leads / 1,858 authors). The pipeline also re-analyzes authors the user already dismissed: nothing checks lead status, `contact_state`, or `do_not_contact` before the profile-fetch → summarize → 6-agent analysis sequence.

## Goals / Non-Goals

**Goals:**
- At most one *active* lead per `(provider_id, author_account_id)`; new qualifying posts attach to the existing lead.
- Skip the analysis pipeline entirely for authors with a prior negative/terminal verdict — before any provider fetch or LLM call.
- Provide an operator-triggered, dry-run-first merge for the ~900 historical duplicates.

**Non-Goals:**
- Analysis-quality changes (gates, thresholds, prompts) — separate changes.
- Fuzzy/cross-provider identity matching (`duplicate_detection` integration is future work).
- UI redesign.

## Decisions

1. **"Active lead" definition**: a lead whose status is NOT `ignored` and not locally deleted (`deleted_at IS NULL`). An `ignored` lead is a standing negative verdict — new posts by that author do not resurrect it and do not create a new one (the scout post is skipped instead). This keeps "ignore" meaningful as an author-level decision without a schema change. *Alternative considered*: per-post ignore with new leads allowed — rejected; it is exactly today's flood behavior.

2. **Attach semantics live in `LeadsService`**: a new `get_active_lead_for_author(provider_id, account_id)` plus attach logic inside `save_lead`. When an active lead exists for the author and the incoming `external_post_id` differs: upsert the post as a `profile_item` (existing behavior), refresh the lead's `updated_at`/`last_seen` context (title/body of the lead row stay those of its primary post), and return the existing lead flagged `attached=True` in the response. Centralizing here means all three creation paths inherit the behavior without duplication. *Alternative*: dedupe only in the scout path — rejected; manual saves would still create duplicates.

3. **Pre-pipeline verdict gate as a `ScoutWatchService` helper**: `check_author_verdict(provider_id, username) -> SkipReason | None` evaluating, in order: `do_not_contact` listing → account `contact_state` in (`contacted`) or `engagement_state` = `engaged` → existing lead with status `ignored`. Called at the top of `scout.analyze_and_decide` (before `fetching_profile`); on a hit the scout post gets `analysis_status='skipped'` and `analysis_reasoning` set to the reason, and the task returns. This both dedupes and saves an entire profile-fetch + 2 summary calls + 6 agent calls per skipped author. *Alternative*: gate at `record_post` — rejected; recording the sighting is still valuable history, only the expensive pipeline is skipped.

4. **Auto-promotion attaches**: in `analyze_and_decide` STEP 8, if the author already has an active lead, call the attach path, link the new `LeadAnalysis` to the existing lead (analysis history accumulates on one lead), and set `scout_post.lead_id` to the existing lead. Watch stats count it as "lead updated" not "lead created" (denormalized `leads_created` unchanged; no schema addition).

5. **Historical merge is a maintenance task, dry-run by default**: `maintenance.merge_duplicate_author_leads(dry_run=True)` groups active leads by `(provider_id, author_account_id)`, keeps the lead with the newest `post_created_at` (newest-post-wins), repoints `lead_analyses.lead_id` and `scout_watch_posts.lead_id` to the survivor, marks losers locally deleted (`deleted_at`, never hard-delete — data-preservation principle), and writes one audit entry per merge group. Dry run reports the plan without mutating. In scope because the 900 existing duplicates otherwise keep polluting the funnel indefinitely.

6. **No schema changes**: uniqueness is enforced in service logic, not a DB constraint, because historical duplicates exist and `author_account_id` is nullable (authorless saves remain post-keyed). A partial unique index can follow after the merge task has run, as future hardening.

## Risks / Trade-offs

- [Service-level uniqueness can race (two workers promoting the same author concurrently)] → acceptable: scout tasks for one author are serialized in practice by per-watch dedupe; a duplicate slipping through is self-healed by the next merge run. A DB constraint is future work.
- [Ignoring a lead now suppresses all future posts by that author] → intended semantics; the scout history still records sightings with skip reasons, and manual add-to-leads remains available as an override (it bypasses the verdict gate deliberately? No — it respects `do_not_contact` but allows overriding an `ignored` verdict, since it is an explicit user action).
- [Merge task repoints foreign keys] → dry-run first, audit-logged, losers soft-deleted so the merge is reversible.
- [Skip gate hides genuinely changed authors (e.g., previously contacted, now re-posting)] → sightings remain visible in watch history; re-engagement is a deliberate user decision from there.

## Migration Plan

1. Deploy code (core + worker together, as worker imports core services).
2. Run `maintenance.merge_duplicate_author_leads` with `dry_run=True`; review the report.
3. Run with `dry_run=False` once; verify lead count ≈ distinct-author count.
4. Rollback: revert code; soft-deleted losers can be restored by clearing `deleted_at` (audit log records merge groups).

## Open Questions

- Should manual `add-to-leads` override an `ignored` author verdict? (Design assumes yes — explicit user action wins — confirm during implementation review.)
- Whether to add the partial unique index after the merge (follow-up hardening, not required for correctness of this change).
