# Tasks: dedupe-leads-by-author

## 1. Author-level lead lookup and attach (core)

- [ ] 1.1 Add `LeadsService.get_active_lead_for_author(provider_id, account_id)` (active = status != 'ignored', `deleted_at IS NULL`); unit tests
- [ ] 1.2 Extend `LeadsService.save_lead`: when the author has an active lead with a different `external_post_id`, upsert the post as a `profile_item`, refresh the lead's `updated_at`, return the existing lead flagged `attached=True`; keep authorless saves on per-post semantics; unit tests
- [ ] 1.3 Surface `attached` in the `POST /leads/save` response schema (additive field) and audit-log the attach; tests

## 2. Pre-pipeline verdict gate (core + worker)

- [ ] 2.1 Add `ScoutWatchService.check_author_verdict(provider_id, username) -> reason | None` checking do_not_contact → contacted/engaged account → ignored lead; unit tests
- [ ] 2.2 Call the gate at the top of `scout.analyze_and_decide` (before `fetching_profile`); on hit set `analysis_status='skipped'` + `analysis_reasoning`, audit-log, return without provider/LLM calls; worker tests asserting no fetch/inference happens
- [ ] 2.3 Manual `add-to-leads` keeps blocking `do_not_contact` but may override an `ignored` verdict (explicit user action); tests

## 3. Auto-promotion attach path (worker)

- [ ] 3.1 In `analyze_and_decide` STEP 8: if the author has an active lead, attach instead of create — link the new `LeadAnalysis` and `scout_post.lead_id` to the existing lead, refresh `updated_at`; tests
- [ ] 3.2 Verify watch history UI renders attached posts correctly (lead link present, no new-lead badge); adjust only if broken

## 4. Historical duplicate merge (worker maintenance)

- [ ] 4.1 Implement `maintenance.merge_duplicate_author_leads(dry_run=True)`: group active leads by `(provider_id, author_account_id)`, survivor = newest `post_created_at`, repoint `lead_analyses.lead_id` and `scout_watch_posts.lead_id`, soft-delete losers, one audit entry per merge group; jobs-ledger idempotency + retry policy
- [ ] 4.2 Unit tests: dry-run mutates nothing and reports groups; applied merge repoints FKs and soft-deletes; idempotent on re-run
- [ ] 4.3 Operator step: run dry-run on prod data, review report, run applied merge; verify lead count ≈ distinct-author count

## 5. Verification

- [ ] 5.1 Integration test: two watches surface different posts by one author → single lead, both scout posts linked to it
- [ ] 5.2 Integration test: ignored author's new post → scout post skipped, zero inference calls (mocked client asserts no invocation)
- [ ] 5.3 Run `pytest` (core + worker) and `npm run lint`; update `leads` and `scout-watch` specs via archive flow when done
