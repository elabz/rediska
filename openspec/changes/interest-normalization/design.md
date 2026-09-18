## Context

`configurable-match-profile` moves interest matching into `interest_matching.match_interests()` and makes it exact on normalised labels and aliases. That is predictable but brittle against free text. The stack already has a local embeddings endpoint (768-dimension vectors, used for hybrid search) that is separate from the inference endpoint and its concurrency gate, plus Redis and MySQL for caching. The preferences agent already returns the author's terms as lists, so the unit of matching is a short phrase, not a document.

Constraints: deterministic and explainable scoring; fail-closed gates must not be affected by fuzzy logic; no cloud services; terms are sensitive adult vocabulary stored verbatim; the user, not the system, owns the profile.

## Goals / Non-Goals

**Goals:**
- Catch wording variants without the user predicting them.
- Turn the stream of extracted terms into a vocabulary the user can curate in minutes.
- Keep every match explainable and reversible.

**Non-Goals:**
- LLM-based matching, shipped taxonomies, automatic alias creation, fuzzy gates (see proposal).

## Decisions

**1. Three passes in fixed order: label, alias, semantic.**
Exact passes are free and unambiguous, so they win. The semantic pass only sees leftovers. Each matched interest counts once, keeping the noisy-OR score honest when an author lists five rope synonyms.

**2. Embedding similarity, not an LLM judge.**
A cosine over cached vectors is deterministic, costs microseconds after first sight, and does not queue behind the single inference slot. An LLM judge would be more accurate on hard pairs but would add a call per analysis, vary between runs, and make preview impossible. *Mitigation for the accuracy gap:* the confirmation loop converts good semantic matches into exact aliases and bad ones into negative pairs, so reliance on the model shrinks as the vocabulary matures.

**3. Threshold is a profile setting with a measured default.**
General-purpose embedding models are weakest on short phrases. Before choosing the default, a calibration script scores a hand-labelled list of term pairs (same, related, unrelated) built from the seeded interests, and reports precision and recall by threshold. The default is set where precision is at least 0.95 on that list; 0.82 is a placeholder until measured. Short terms are embedded inside a fixed carrier phrase ("interest: <term>") to stabilise vectors.

**4. Semantic matches score at full weight immediately.**
Waiting for confirmation would make the feature useless on day one. The risk of a wrong match is bounded: it can raise a priority tier but cannot pass a gate or change a recommendation, and it is visible on the lead with the original wording. *Alternative:* half weight until confirmed. Rejected as harder to explain than "it matched, here is why".

**5. Gates never use semantic matching.**
A deal-breaker fail removes a post from consideration. That must only happen on wording the user has explicitly listed or confirmed.

**6. Vector cache in MySQL, hot copy in Redis.**
Key is (normalised text, model name). MySQL makes the cache survive Redis flushes and model comparisons; Redis avoids a query per term. A model change invalidates nothing; new keys are filled lazily. Profile label vectors are embedded at profile save.

**7. Vocabulary upsert is inline, tiny, and never fails the analysis.**
One `INSERT ... ON DUPLICATE KEY UPDATE` per term at the end of preferences post-processing, wrapped so an error is logged and swallowed. Resolution stored on the term is "as of last seen"; the authoritative match for an analysis is what was stored with that analysis.

**8. Confirmation edits the profile through the normal save path.**
Aliases and negative pairs are part of the profile document, so they are versioned, validated, previewable, and restorable like everything else. Several confirmations in one session are batched into one new version.

**9. Hashtag splitting uses the known vocabulary, not a dictionary.**
`#ropebondage` is split by greedy match against known labels, aliases, and confirmed terms. Unknown joined tags are left intact and show up in the vocabulary as themselves. Known input quirk: title tags arrive joined (for example `#newyork`).

## Risks / Trade-offs

- [False semantic matches inflate scores] → measured threshold, negative pairs, visible explanation, no gate effect, agreement on the preferences dimension tracked by profile version.
- [Embedding model is poor on adult vocabulary] → the calibration list is built from the real seeded interests; if precision cannot reach 0.95 at useful recall, ship passes 1 and 2 plus the vocabulary and leave the semantic pass off by default.
- [Vocabulary grows without bound] → it is one small row per distinct term; the UI sorts by count and hides singletons by default.
- [Embeddings outage] → exact-only fallback recorded on the result; no retry storm.
- [Determinism across cache states] → the same text and model always yield the same vector, so a cold cache changes latency, not results.

## Migration Plan

1. Requires `configurable-match-profile` deployed and archived.
2. Migration for `interest_terms` and the vector cache; add `semantic_threshold`, `semantic_enabled`, and `negative_pairs` to the profile schema with defaults that keep current behaviour (`semantic_enabled=false`).
3. Ship normalisation and vocabulary; run the backfill dry run, then live.
4. Run the threshold calibration; set the default; enable the semantic pass; check preview for the expected rise in matched leads.
Rollback: set `semantic_enabled=false` in the profile (a restore), no deploy needed.

## Open Questions

- Should confirmed aliases also be fed back into the preferences prompt as extraction hints? Proposed: no, keep the prompt free of profile content.
- Should the vocabulary show co-occurrence ("authors who mention X also mention Y") to suggest new interests? Proposed: follow-up once counts exist.
