## Why

Hybrid search is specified and built, but it has never been semantic: nothing dispatches any `embed.*` task, so all 58,649 documents in `rediska_content_docs_v1` have no vector and every search silently falls back to BM25. Lead posts are not in the index at all, because nothing enqueues `index.upsert_content` for them. A working vector index is the missing foundation for several things the user wants: searching by meaning, "more like this" from any post, lead, profile or message, a semantic second pass for copy detection, the pending `lead-affinity-signal` change, and retrieval of past intros for `voice-matched-replies`.

## What Changes

- **The embedding pipeline is wired end to end.** Every indexed document type gets a vector: `lead_post`, `profile_item` posts, one merged `account_comments` document per account (comments are short, so an account's recent comments are embedded together up to the input limit), `profile_snapshot`, `message`, and a new `scout_post` type for analysed scout posts. Indexing enqueues embedding; embedding failure never blocks indexing and is retried by a sweeper.
- **Lead posts and analysed scout posts are indexed.** `save_lead`, scout promotion and analysis completion enqueue indexing; a backfill covers existing rows.
- **One text-preparation rule.** Title plus resolved body, truncated to a token budget the embeddings server accepts. Measured: the server rejects inputs above ~512 tokens, so the default budget is 1,400 characters; documents above it are embedded as the mean of up to 4 chunk vectors. Model name and text-prep version are stored on the document so a model change can be detected and re-embedded.
- **Vectors stop bloating the index.** The `embedding` field is excluded from `_source` (measured: 15.8 KB per document with it, ~4 KB without). This needs a new index version and a reindex, done behind an alias.
- **A similarity API: "more like this".** `POST /similar` takes an entity reference (`doc_type` + id) or raw text and returns the nearest documents with cosine score, filterable by doc type, author (same / other / any), location, date range and lead outcome. It answers with BM25 `more_like_this` when the source has no vector yet, and says which method was used.
- **"More like this" in the UI.** A Similar action on lead detail, lead cards, scout history posts, needs-review items, profile items and search results opens a panel of neighbours with score, author, date, status and verdicts. Global search gains a working mode switch (hybrid / text / meaning) and shows when semantic ranking was unavailable instead of degrading silently.
- **Semantic second pass for copies.** For analysed posts, neighbours by a different author at cosine ≥ 0.95 that the fingerprint pass did not cluster are shown as "probable rewrite" and, when `post-fingerprint-dedupe` is present, offered as a cluster suggestion the human accepts or rejects.
- **Health and backfill.** `/ops` shows vector coverage per doc type, embed queue depth and last error; `embed.backfill` embeds existing documents with a dry run, paced so live analysis keeps priority on the GPU host.

## Non-goals

- No cloud embedding or vector service; everything stays on the local llama.cpp endpoint and local Elasticsearch.
- No embedding of every post seen by scout runs. Fingerprints cover that at 0.5 KB per post; vectors are for content we keep (tens of thousands of documents, not millions).
- No change to ranking of leads or to any gate; that is `lead-affinity-signal`.
- No content filtering or safe-search mode; NSFW content is embedded and returned verbatim.
- No second vector store (pgvector, FAISS, Qdrant).

## Capabilities

### New Capabilities
- `similarity-search`: the `/similar` API, its filters and fallbacks, UI entry points, and the probable-rewrite pass.

### Modified Capabilities
- `search-indexing`: all indexed types are embedded, lead and scout posts are indexed, text preparation and model stamping are defined, vectors are excluded from `_source`, silent BM25 fallback becomes visible, coverage is observable, backfill exists.

## Impact

- **ES**: new index `rediska_content_docs_v2` behind alias `rediska_content_docs`; additive fields `embedding_model`, `embedding_prep`, `embedded_at`, `author_username`, `location`, `outcome_label` (reserved for lead-affinity). Heap stays 1 GB for the current corpus (~110k vectors: 55k messages, 45k posts, 3k merged comment documents, leads and scout posts; about 100 MB of int8 HNSW); `docs/deploy.md` documents sizing: ~1 GB page cache and ~4 GB disk per million vectors.
- **Worker**: implement the stubbed `lead_post` branch and the other types in `embed.generate_for_entity`; `embed.sweep_missing` (beat, every 10 min, bounded batch); `embed.backfill`; `index.reindex_to_version`.
- **Core**: `domain/services/similarity.py`, `api/routes/similar.py`, search response carries `semantic_used`; enqueue hooks in leads, scout, analysis, message ingest.
- **Web**: `SimilarPanel`, search mode switch, `/ops` coverage card, BFF proxy `/api/core/similar`.
- **GPU cost** (measured, 43 docs/s): full backfill of ~110k documents ≈ 45 minutes; steady state under a minute per day.
- **Relationship to other changes**: supersedes task group "lead posts get embeddings" of `lead-affinity-signal` (that change should drop those tasks and depend on this one); `voice-matched-replies` uses `/similar` for example retrieval; `post-fingerprint-dedupe` is optional for the rewrite suggestions.
