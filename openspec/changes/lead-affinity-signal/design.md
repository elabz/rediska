## Context

Signals already recorded: lead status (`ignored`, `contacted`), account `contact_state` / `engagement_state`, needs-review `dismissed_at` / `triaged_at`, and append-only human evaluations. None of them feeds ranking. The infrastructure for similarity exists: a local embeddings endpoint, a 768-dimension cosine `dense_vector` field in the Elasticsearch index, and a kNN search path used by hybrid search. The gap is that `lead_post` documents are indexed for text but never embedded: `tasks/embed.py` handles `message` and leaves `lead_post` as a commented stub.

Constraints: agents and tasks must not read inbox content, so outcomes come from state fields only; verdicts are content-scoped, not person-scoped; analysis results are never rewritten; `needs_review` exists for the human and must not be thinned by automation; nothing leaves the LAN.

## Goals / Non-Goals

**Goals:**
- Let past decisions order future work, with an explanation a human can check.
- Make it measurable whether the signal is any good.
- Add no LLM load.

**Non-Goals:**
- Any automated decision, trained model, person-level judgement, or use of message content (see proposal).

## Decisions

**1. Nearest neighbours over labelled exemplars, not a trained classifier.**
With a few hundred to a few thousand labelled posts, kNN is as good as anything trainable, needs no training step, updates the moment a label changes, and explains itself ("similar to these three leads"). *Alternatives:* centroid of positives minus centroid of negatives: cheaper but blurs distinct kinds of good leads into one average and cannot explain. Logistic regression on vectors: opaque, needs retraining and versioning.

**2. Exemplars live in Elasticsearch, on the existing lead documents.**
`outcome_label` and `outcome_weight` are additive keyword/float fields. Scoring is one filtered kNN query (`doc_type = lead_post`, `outcome_label exists`, `local_deleted = false`, `account_id != author`). No second vector store. Scout posts are not indexed; their text is embedded on the fly for scoring and only the resulting score is stored.

**3. Similarity-weighted positive share.**
`affinity = Σ sim(positive) / Σ sim(all k)`. Bounded 0 to 1, robust to class imbalance only if both classes are present, hence the minimum of 30 exemplars per class before any score is shown. Engaged exemplars carry `outcome_weight` 1.0, contacted 0.7, evaluation-agree 0.7, negatives 1.0; weights multiply similarity. *Alternative:* raw count share. Rejected: a neighbour at 0.55 similarity should not count like one at 0.9.

**4. Same-author exclusion.**
Reposts by one author are near-duplicates. Without exclusion, a contacted author's repost would score about 1 by matching itself, which says nothing about the content.

**5. Score at analysis time, store, do not recompute on read.**
Stored scores keep list queries cheap (the Leads list must stay at a fixed number of batched queries) and make the calibration table leak-free: the band used is the score the lead had before its own outcome existed. Scores age as exemplars accumulate, so a backfill task refreshes active leads and untriaged needs-review posts; stale scores (different model name) are flagged.

**6. Label maintenance is event-driven with a reconciler.**
Hooks in lead status change, contact/engagement state change, needs-review dismiss, and evaluation record call `refresh_outcome_label(lead_id)`, which recomputes the label from current state and updates the ES document through the existing index task. A daily reconcile pass recomputes labels for leads changed in the last two days to heal missed events. Label derivation reads state columns only.

**7. Embedding text and model hygiene.**
Text is `title + "\n\n" + resolved body`, including the structured details block prepended for external listings, truncated to the model limit. If the embeddings model uses task prefixes (nomic-style `search_document:`), the same prefix is used for exemplars and queries. The model name is stored with every score.

**8. Opt-in sort only.**
Default orderings do not change. The user has been explicit that the Leads list is a list, not a conveyor, and that needs-review is theirs to judge. Affinity is a column they can sort by. Whether it should later break ties inside a priority tier is an open question to answer with the calibration table in hand.

**9. Bias is surfaced, not hidden.**
A similarity signal trained on one's own choices narrows over time. Because it never filters, never gates, and is not the default sort, the narrowing can only happen if the user chooses the sort. The calibration table shows whether low-affinity leads that were contacted anyway did well, which is the evidence of a blind spot.

## Risks / Trade-offs

- [Feedback loop: sorting by affinity yields more positives that look alike] → opt-in sort, no filtering, calibration table, same-author exclusion.
- [Labels are noisy: "ignored" can mean "too far", not "wrong kind of post"] → gates already remove most far and wrong-gender posts before they become leads; evaluation verdicts are weighted as cleaner labels; minimum exemplar counts.
- [Embedding model weak on this vocabulary] → the calibration table is the acceptance test; if bands do not separate outcomes, leave the feature off.
- [ES document without embedding, or mapping drift] → additive mapping update, backfill with dry run, smoke check counting lead documents with and without vectors.
- [Extra work in the analysis task] → one embedding and one kNN call, wrapped so failure nulls the score and never fails the analysis.
- [Privacy] → exemplar text is the public post; no message content is touched; everything stays in local ES.

## Migration Plan

1. Migration for the four nullable columns; additive ES mapping update.
2. Implement the `lead_post` embed branch; run `embed.backfill_lead_posts` dry run, then live.
3. Ship label derivation and run the reconciler over all leads once.
4. Enable scoring with `LEAD_AFFINITY_ENABLED=true` (wired in `docker-compose.yml` for core and worker); run `affinity.backfill` for active leads.
5. Ship UI and calibration table. Review the table after two to four weeks.
Rollback: set the flag false; stored data is inert.

## Open Questions

- After the calibration table shows separation, should affinity break ties within a priority tier by default? Proposed: decide then, as its own small change.
- Should needs-review dismissals count as negatives at full weight? A dismissal often means "gate was right", which is about the gate, not the content. Proposed: weight 0.5.
- Should source-discovery trials report mean affinity as part of their yield? Proposed: yes if both changes land, as a follow-up.
