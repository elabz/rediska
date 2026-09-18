## 1. Foundations

- [ ] 1.1 Confirm `configurable-match-profile` is deployed and archived; rebase on its `interest_matching.py`
- [ ] 1.2 Migration: `interest_terms`, `interest_term_vectors`; upgrade and downgrade tested
- [ ] 1.3 Extend the profile schema with `semantic_enabled` (default false), `semantic_threshold`, `negative_pairs`; validation and defaults so existing versions load unchanged

## 2. Lexical normalisation

- [ ] 2.1 Normaliser: case, whitespace, punctuation, leading `#`, plural and suffix folding, stop-phrase stripping; original wording preserved
- [ ] 2.2 Vocabulary-driven hashtag splitting
- [ ] 2.3 Unit tests including joined hashtags, stop-phrases, idempotence, and non-ASCII input

## 3. Semantic pass

- [ ] 3.1 Vector cache service (MySQL source of truth, Redis hot copy), keyed by normalised text and model name; batch embed of misses with a carrier phrase
- [ ] 3.2 Embed profile labels and aliases on profile save
- [ ] 3.3 Semantic pass in `match_interests()`: leftovers only, best match at or above threshold, negative pairs respected, one count per interest, method and similarity recorded
- [ ] 3.4 Exact-only fallback on embeddings error or timeout, recorded as `semantic_matching: "skipped"`, no in-analysis retry
- [ ] 3.5 Deal-breaker gate uses normalisation and aliases only; test that a semantically close term never fails it
- [ ] 3.6 Unit tests with a stub embedder: variant matches, below threshold, rejected pair, determinism across cold and warm cache, outage fallback

## 4. Threshold calibration

- [ ] 4.1 Build a synthetic labelled pair list (same / related / unrelated) from the seeded interests; no scraped content
- [ ] 4.2 Script reporting precision and recall by threshold against the local embeddings endpoint
- [ ] 4.3 Set the default threshold at precision ≥ 0.95, or record the decision to ship with the semantic pass off

## 5. Vocabulary

- [ ] 5.1 Inline upsert of extracted terms after preferences post-processing; errors logged and swallowed
- [ ] 5.2 Backfill task over stored preferences outputs: `jobs` ledger, retry policy, dry run by default, routed by registered task name with a routing-test row
- [ ] 5.3 Routes under `/match-profile/vocabulary`: list with filters, sort, cursor; confirm, reject, map, create interest, ignore; batched into one profile version per request; `audit_log` on each
- [ ] 5.4 Integration tests: confirm becomes alias, reject becomes negative pair, create interest, ignore hides from unmatched, audit rows

## 6. Web

- [ ] 6.1 BFF proxies for vocabulary routes
- [ ] 6.2 Vocabulary tab: list, filters, counts, similarity, actions, backfill trigger; loading, empty, error states
- [ ] 6.3 Match-method indicator on chips; original wording on lead detail
- [ ] 6.4 Vitest and lint clean

## 7. Rollout

- [ ] 7.1 Full core and worker suites green in Docker
- [ ] 7.2 Deploy with `semantic_enabled=false`; run backfill dry run, then live
- [ ] 7.3 Enable the semantic pass via a profile save; check preview for the change in matched leads and review the first page of semantic matches in the Vocabulary tab
- [ ] 7.4 Update CLAUDE.md and README; sync specs, diff, archive
