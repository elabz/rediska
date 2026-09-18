## 1. Embedding lead posts

- [ ] 1.1 Implement the `lead_post` branch in `embed.generate` (title plus resolved body, truncation, model prefix if required); remove the commented stub
- [ ] 1.2 Enqueue embedding on lead save, auto-promotion, manual add-to-leads, and when a link-only body is resolved later
- [ ] 1.3 `embed.backfill_lead_posts`: batches, `jobs` ledger, retry policy, dry run by default, routing-test row
- [ ] 1.4 Tests: text assembly, truncation, failure does not fail the save, backfill dry run writes nothing

## 2. Schema and mapping

- [ ] 2.1 Alembic migration: nullable `affinity_score`, `affinity_json` on `lead_posts` and `scout_watch_posts`
- [ ] 2.2 Additive ES mapping: `outcome_label`, `outcome_weight`; mapping update applied idempotently at startup
- [ ] 2.3 Config `LEAD_AFFINITY_ENABLED`, `LEAD_AFFINITY_MIN_EXEMPLARS`, `LEAD_AFFINITY_K` in `config.py`, `.env.example`, and both compose environment blocks

## 3. Outcome labels

- [ ] 3.1 `lead_affinity.derive_outcome_label(lead)` from status, account states, needs-review dismissal, effective evaluations; precedence rules; exclusions for soft-deleted and do-not-contact
- [ ] 3.2 `refresh_outcome_label` hooks in lead status change, contact/engagement state change, needs-review dismiss, evaluation record
- [ ] 3.3 Daily reconcile pass inside an existing maintenance window, `jobs` ledger
- [ ] 3.4 Unit tests for every scenario in the spec, including revive clears label, expired unlabelled, engaged outranks ignore; test that no message or conversation table is queried

## 4. Affinity scoring

- [ ] 4.1 `compute_affinity(text, author_account_id)`: embed, filtered kNN, weighted positive share, top-three explanation, exemplar counts, model name
- [ ] 4.2 Null with reason for insufficient history, embedding unavailable, search unavailable
- [ ] 4.3 Call at the end of `multi_agent_analysis.analyze_lead` and `scout.analyze_and_decide` / `reanalyze_post`, wrapped so failure never affects the analysis
- [ ] 4.4 `affinity.backfill` for active leads and untriaged needs-review posts; stale detection by model name; dry run by default
- [ ] 4.5 Tests with a stub embedder and an in-memory exemplar set: high and low affinity, same-author exclusion, minimum exemplars, failure paths
- [ ] 4.6 Guard tests: affinity is absent from `evaluate_gates`, `compute_score`, `derive_priority`, and the auto-promotion decision

## 5. API

- [ ] 5.1 Affinity fields on lead list (batched, no extra per-row query), lead detail, scout post, needs-review items
- [ ] 5.2 `sort=affinity` on `GET /leads` (nulls last, then recency) and on `GET /scout-watches/needs-review` with a matching keyset cursor
- [ ] 5.3 Feature-off behaviour: fields omitted, sort falls back
- [ ] 5.4 Calibration report: outcome rates per affinity band from stored scores; test for no leakage
- [ ] 5.5 Tests for ordering, cursor stability, query count unchanged on the lead list

## 6. Web

- [ ] 6.1 Affinity badge with "similar to" popover linking the three exemplar leads; "not enough history" and stale states
- [ ] 6.2 Sort option on Leads and on the Needs review tab
- [ ] 6.3 Calibration panel table on `/ops`
- [ ] 6.4 Vitest and lint clean

## 7. Rollout

- [ ] 7.1 Full core and worker suites green in Docker
- [ ] 7.2 Deploy with the flag off; run the embedding backfill (dry run, then live); verify counts of lead documents with vectors
- [ ] 7.3 Run the label reconciler once; report exemplar counts per label
- [ ] 7.4 Enable the flag; run `affinity.backfill`; spot-check explanations on a handful of leads
- [ ] 7.5 Update CLAUDE.md and README; sync specs, diff, archive
