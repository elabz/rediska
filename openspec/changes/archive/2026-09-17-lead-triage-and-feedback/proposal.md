# Proposal: lead-triage-and-feedback

## Why

The lead funnel produces more output than it helps the user work: 2,739 of 2,754 scout-created leads sit unworked at status `new`, while 3,585 `needs_review` scout posts (avg confidence 0.51) never surface anywhere except buried per-watch history. Signals that would enable triage are computed and then thrown away — the meta agent's `priority_level` and the preferences `compatibility_score` are discarded — and nothing compares the user's actual verdicts (ignored/contacted/engaged) against the analysis output, so thresholds and prompts are tuned blind.

## What Changes

- **Priority tiering**: persist a priority tier on `lead_posts`, derived from the preferences `compatibility_score`, decision-gate margins, and the meta agent's `priority_level`. The Leads page sorts by priority then recency by default and badges compatibility.
- **Needs-review queue**: a first-class view (Leads page tab/filter) listing scout posts whose analysis recommendation is `needs_review`, with one-click promote-to-lead (reusing the existing add-to-leads endpoint) and dismiss actions. Scout history retention is adjusted so untriaged `needs_review` posts are not purged out from under the queue.
- **Lead freshness / auto-expiry**: a scheduled maintenance task auto-expires scout-sourced leads still `new` after a configurable N days (default 14). Expired leads are excluded from the default list view; every expiry is audit-logged. A one-time backfill (dry-run first) clears the existing ~2.7k backlog.
- **Calibration/feedback report**: a weekly beat job computing per-watch and overall precision signals — suitable→ignored rate, suitable→contacted/engaged rate, gate-failure distribution, dimension failure rates — from data already recorded (`lead_posts` status transitions, `analysis_dimensions`, `audit_log`). Reports are stored and rendered on the Ops page.

## Capabilities

### New Capabilities

_None — all changes extend existing capabilities._

### Modified Capabilities

- `leads`: status lifecycle gains `expired`; listing gains priority-first default ordering, priority/compatibility fields, and default exclusion of expired leads; a needs-review triage view is added alongside the lead list.
- `scout-watch`: analysis results must persist priority inputs (`priority_level`, `compatibility_score`) onto created leads; auto-promotion records them; retention cleanup must preserve untriaged `needs_review` posts; a dismiss action marks a needs-review post triaged.
- `ops-jobs`: a weekly calibration report job and its storage/display are added to the ops surface.

## Impact

- **DB / migrations**: new columns on `lead_posts` (`priority`, `compatibility_score`, `expired_at` or status enum extension), a `triaged_at`/`dismissed_at` marker on `scout_watch_posts`, and a small `calibration_reports` table (or JSON report rows).
- **Core**: `leads.py` (status enum, listing order/filters), `scout_watches.py` routes (needs-review listing + dismiss), `scout_watch.py` service (persist priority fields, retention rules), new report service; audit entries for expiry/dismiss.
- **Worker**: new `maintenance.expire_stale_leads` and `maintenance.generate_calibration_report` beat entries; `scout.analyze_and_decide` stores priority fields when creating leads.
- **Web**: Leads page (priority sort, badges, needs-review tab, expired filter), Ops page (report panel).
- **No new external dependencies.**

## Non-goals

- No ML or automated threshold tuning — the calibration report informs manual tuning only.
- No changes to the analysis gates or decision rules themselves (covered by the sibling change `deterministic-lead-gates`).
- No notification system (email/push) for high-priority leads or reports.
- No changes to manual lead saving from Browse.
