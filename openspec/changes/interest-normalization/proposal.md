## Why

Once interests are matched in code (`configurable-match-profile`), matching is exact on labels and aliases. Authors do not write to a vocabulary: the same interest arrives as "rope", "rope bunny", "shibari", "being tied up", "#ropebondage". Exact matching will miss most of these unless the user predicts every spelling as an alias, so compatibility scores would understate real matches and good leads would sit in lower tiers. The system also throws away what it learns: every analysis extracts terms, but nothing accumulates them, so the user never sees which interests authors mention most or which frequent terms the profile fails to recognise.

## What Changes

- **A term vocabulary that accumulates.** Every extracted hobby and kink term is recorded in an `interest_terms` table with its normalised form, occurrence count, first and last seen, and how it resolved: to a profile interest (by label, alias, or semantic match), to nothing, or to "ignored".
- **Semantic matching as a second pass.** Terms that do not match exactly are compared by embedding similarity (local embeddings endpoint) to the profile's interest labels and aliases. A similarity at or above the profile's threshold counts as a match, labelled `semantic` with its similarity, and scores like any other match. Term and interest vectors are cached, so a term is embedded once.
- **Human confirmation closes the loop.** A Vocabulary tab on the match profile page lists frequent terms with their resolution. The user can confirm a semantic match (it becomes an alias, exact from then on), reject it (a stored negative pair that never matches again), map an unmatched term to an interest, create a new interest from it, or mark it ignored.
- **Lexical normalisation before either pass.** Hashtag and joined-tag splitting (`#ropebondage`), plural and simple suffix folding, and stop-phrase stripping ("into", "love", "big fan of"), applied identically to extracted terms and profile labels.
- **Degrades safely.** If the embeddings endpoint is unavailable, matching falls back to exact only, the analysis still completes, and the result records that semantic matching was skipped.
- **Explainable on the lead.** Each matched interest shows how it matched (label, alias, or semantic with the original wording).

## Non-goals

- No LLM call for matching. Matching stays deterministic given the same profile, cache, and embeddings model.
- No automatic alias creation. A semantic match affects scores immediately, but only the user turns it into an alias or rejects it.
- No interest taxonomy or ontology shipped with the product; the vocabulary is whatever the user's data produces.
- No change to gates other than the deal-breaker gate gaining the same normalisation (exact and confirmed aliases only; semantic matching is never used to fail a gate).
- No cloud embedding service; vectors come from the local endpoint only.
- No re-scoring of stored analyses when the vocabulary changes; preview from the match-profile change shows the effect.

## Capabilities

### New Capabilities

- `interest-normalization`: lexical normalisation, semantic matching with cache and threshold, the accumulating vocabulary, negative pairs, the confirmation workflow, and the Vocabulary UI.

### Modified Capabilities

_None. `match-profile` is introduced by `configurable-match-profile`, which must be archived first; this change then extends it through the new capability rather than a delta._

## Impact

- **Depends on** `configurable-match-profile` (uses `match_interests()` and the profile schema; adds `semantic_threshold` and negative pairs to the profile document).
- **Database**: `interest_terms` (normalised term unique, counts, resolution, resolved interest label, method, similarity, timestamps) and `interest_term_vectors` (term or label, model name, vector) or a Redis cache with the same key; migration after the match-profile migration.
- **Core**: `interest_matching.py` gains the normalisation and semantic passes; new `interest_vocabulary.py`; embeddings client batch call; routes under `/match-profile/vocabulary`.
- **Worker**: vocabulary upsert happens inline at the end of the preferences post-processing (one upsert per term); an optional backfill task reads stored preferences outputs to seed the vocabulary.
- **Web**: Vocabulary tab, match-method label on matched-interest chips.
- **Load**: a handful of short embedding calls per analysis on first sight of a term, none afterwards. The embeddings endpoint is separate from the inference gate.
