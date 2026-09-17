# Design: lead-triage-and-feedback

## Context

Scout watches create leads faster than a single user can work them (2,739 unworked `new` leads; watches run every 5 minutes). Analysis already computes triage-grade signals — meta `priority_level`, preferences `compatibility_score`, per-rule pass/fail — but `scout.analyze_and_decide` discards them after the suitable/confidence check. `needs_review` outcomes (3,585 posts) live only in `scout_watch_posts.dimension_results_json`, in a UI buried under per-watch history, and are deleted by the 3-day retention cleanup before anyone can look. User verdicts (status changes to ignored/contacted, engagement state on accounts) are recorded in `lead_posts`, `external_accounts`, and `audit_log` but never aggregated.

## Goals / Non-Goals

**Goals:**
- Make the Leads page a ranked work queue, not an unbounded log.
- Surface `needs_review` posts for one-click human triage before retention purges them.
- Keep the lead list fresh automatically (expiry), with a safe backfill for the existing backlog.
- Produce a weekly precision report so gate/threshold tuning is evidence-driven.

**Non-Goals:**
- Changing how recommendations/confidence are computed (sibling change `deterministic-lead-gates`).
- Automated tuning, notifications, multi-user workflow.

## Decisions

1. **Priority as a stored small enum + score, computed at lead creation.**
   `lead_posts.priority` ENUM('high','medium','low') + `lead_posts.compatibility_score` FLOAT. Derivation (in code, not LLM): start from meta `priority_level`; demote one tier when `compatibility_score < 0.5`; promote to `high` when `compatibility_score ≥ 0.7` and all gates passed cleanly. Stored at creation (scout path and analyze-multi path) rather than computed at query time — the list must sort by it with an index, and analyses are immutable snapshots anyway. *Alternative rejected:* computing at render time from `dimension_results_json` — un-indexable and couples the UI to analysis internals.

2. **Expiry is a status, not a delete.**
   Extend the `lead_posts.status` enum with `expired` (preserves no-delete principle and audit history; `deleted_at` stays reserved for user hides). `maintenance.expire_stale_leads` (daily beat, after the backup window) sets `status='expired'` where `lead_source='scout_watch' AND status='new' AND created_at < now() - N days`, one audit row per batch with the affected ids. N from env `LEAD_EXPIRY_DAYS` (default 14, 0 disables). Manual leads never auto-expire. Backfill = the same task invoked once with an explicit flag; it MUST support `dry_run=true` returning the would-expire count first. Default `GET /leads` excludes `expired` unless `status=expired` is requested. *Alternative rejected:* reusing `ignored` — conflates a human verdict with a timeout and poisons the calibration report's suitable→ignored precision signal.

3. **Needs-review queue reads from `scout_watch_posts`, not a new table.**
   New route `GET /scout-watches/needs-review` (cross-watch, cursor-paginated): posts with `analysis_recommendation='needs_review'` and `dismissed_at IS NULL`, newest first, joined with watch name and dimension results for display. Actions: promote → existing `add-to-leads` endpoint (sets `triaged_at`); dismiss → new `POST /scout-watches/posts/{post_id}/dismiss` setting `dismissed_at` (audit-logged). UI: a "Needs review" tab on the Leads page showing the queue count. *Alternative rejected:* promoting needs_review posts into `lead_posts` with a special status — floods the leads table with exactly the noise this change is removing.

4. **Retention must not race the queue.**
   `maintenance.cleanup_scout_watch_history` changes: posts with `analysis_recommendation='needs_review'` and `dismissed_at IS NULL` are exempt from the default retention window and instead purge after a longer `SCOUT_NEEDS_REVIEW_RETENTION_DAYS` (default 14). Dismissed/triaged posts follow the normal 3-day window from their `dismissed_at`/`triaged_at`.

5. **Calibration report is a computed snapshot row.**
   New table `calibration_reports` (id, period_start, period_end, report_json, created_at). Weekly beat task `maintenance.generate_calibration_report` computes, per watch and overall: suitable→ignored rate, suitable→contacted rate, contacted→engaged rate (from `external_accounts.engagement_state`), needs_review promote/dismiss counts, gate-failure distribution (parsed from stored meta reasoning / dimension outputs), and per-dimension failure rates (from `analysis_dimensions.status`). Exposed via `GET /ops/calibration-reports` (+ latest), rendered as a panel on `/ops`. Plain SQL aggregation — no LLM involvement. *Alternative rejected:* computing live on page load — the queries scan several large tables and the historical trend (report per week) is the point.

## Risks / Trade-offs

- [Expiry backfill mass-expires ~2.7k leads in one shot] → mandatory dry-run mode returning counts; batch audit logging; expired is reversible (status can be set back manually).
- [Priority derivation depends on analyses created before this change, which lack stored fields] → old leads get `priority=NULL`, sorted after prioritized ones; no backfill of priority (analysis JSON exists on `dimension_results_json`/`lead_analyses` if ever wanted).
- [Longer needs_review retention grows `scout_watch_posts`] → bounded by the 14-day cap; dismissals shrink it; report tracks queue size.
- [Gate-failure distribution parsing from LLM reasoning text is fuzzy until `deterministic-lead-gates` lands] → report marks that section "best-effort" until structured gate results exist; the two changes compose cleanly (deterministic gates will store structured pass/fail the report can consume).

## Migration Plan

One alembic migration: `lead_posts.priority`, `lead_posts.compatibility_score`, status enum + `expired`, `scout_watch_posts.dismissed_at`, `scout_watch_posts.triaged_at`, `calibration_reports` table, index on `(status, priority, created_at)`. Deploy core+worker+web together; run backfill dry-run, review count, then run for real. Rollback: revert code; new columns/status values are inert.

## Open Questions

- Exact demote/promote thresholds for priority derivation (0.5/0.7 chosen from the observed compatibility_score rubric; revisit after the first calibration report).
- Whether the Ops panel or the Scout Watch settings page is the better home for per-watch report rows (start with Ops; both read the same endpoint).

## Implementation Notes (apply, 2026-09-17)

Deviations from the decisions above, made during implementation:

- **Retention (Decision 4)**: no `SCOUT_NEEDS_REVIEW_RETENTION_DAYS`. Since `dedupe-leads-by-author`, cleanup never deletes a post that carries analysis output (it detaches it from the expiring run), which already keeps untriaged needs-review posts available indefinitely. Purging dismissed/triaged posts after 3 days would have deleted analysis results, which is not allowed. The queue reads by `watch_id`, so detached posts still appear.
- **Expiry backfill (Decision 2)**: rather than a separate backfill flag, the task refuses every live run (including the nightly beat) until a dry run has completed once (`jobs` ledger key `maintenance.expire_stale_leads:dry_run`). `expired` is excluded from author-level "active lead" dedupe but is not an ignore verdict. The UI revives to `saved`, because a revived `new` scout lead would re-expire the next night.
- **Priority**: attached posts update the existing lead's tier (latest analysis wins, as for recommendation/confidence). Missing meta level starts at `medium`; missing compatibility neither promotes nor demotes. Manual promotion from the queue derives the tier from the post's stored results.
- **Expiry off by default (2026-09-17)**: keeping leads costs ~10 MB and does not slow the list, so `LEAD_EXPIRY_DAYS` defaults to 0 and the Leads page instead filters by post date (7d / 14d / 30d / All, default 14d). The expiry task remains for opt-in use. List author enrichment was batched (3 queries per page instead of ~4 per lead), which was the real latency cost.
- **Calibration report**: plain Python aggregation (portable to SQLite tests), not SQL. Lead verdict rates use a 28-day lead cohort ending at the period end (verdicts lag creation); post/dimension metrics use the 7-day period. Per-watch dimension failures come from dimensions missing in stored scout results; overall attempt failure rates from `analysis_dimensions`. Weekly beat Monday 06:00 UTC plus an on-demand `POST /ops/calibration-reports/generate`.
