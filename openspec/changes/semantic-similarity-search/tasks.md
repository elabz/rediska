## 1. Index version and mapping

- [ ] 1.1 Mapping v2: `_source.excludes: ["embedding"]`, fields `embedding_model`, `embedding_prep`, `embedding_text_hash`, `embedded_at`, `author_username`, `location`, `outcome_label`; alias `rediska_content_docs`
- [ ] 1.2 All readers and writers address the alias; `ensure_index` creates v2 + alias on a clean host
- [ ] 1.3 `index.reindex_to_version`: rebuild from MySQL in batches, per-type parity check, alias switch, `jobs` ledger

## 2. Embedding pipeline

- [ ] 2.1 `prepare_embedding_text()` with truncation and paragraph chunking; unit tests (short, long, no paragraphs, empty)
- [ ] 2.1a Task prefixes (`search_document:` / `search_query:`) in one place, recorded in `embedding_prep`; re-measure the 0.80 and 0.95 thresholds with prefixes on
- [ ] 2.2 `EmbeddingsClient`: never send over-limit input; chunk-mean helper; surface HTTP 500 "too large" as a typed error
- [ ] 2.3 Implement `lead_post`, `scout_post`, `profile_item`, `profile_snapshot` branches in `embed.generate_for_entity`; vector write that never reads the vector back; skip when text hash unchanged
- [ ] 2.3a `account_comments` document: merge newest first with community prefix up to `EMBED_MAX_CHARS`, rebuild on profile ingest, re-embed only on text-hash change; comments themselves indexed text-only; tests on synthetic comments
- [ ] 2.4 `IndexingService.scout_post_to_document`; remove `scout_post` document on promotion
- [ ] 2.5 Enqueue chain index → embed; hooks in `LeadsService.save_lead`, scout promotion, `analyze_and_decide` completion, message ingest, profile analysis; `EMBEDDINGS_ENABLED` flag in config, `.env.example` and compose blocks
- [ ] 2.6 `embed.sweep_missing` beat entry (10 min, bounded), `embed.backfill` (dry run, cancellable, `EMBED_MAX_CONCURRENT` semaphore, inference-gate-aware pause)
- [ ] 2.7 Task routing test covers the new task names

## 3. Search honesty

- [ ] 3.1 `semantic_used` / `semantic_unavailable_reason` in `SearchService` and the response schema; `vector` mode errors instead of falling back
- [ ] 3.2 kNN filter on `embedding_model`
- [ ] 3.3 `/search` page mode switch and notice

## 4. Similarity API

- [ ] 4.1 `domain/services/similarity.py`: by reference, by text, filters, cosine conversion, `more_like_this` fallback
- [ ] 4.2 `POST /similar` route + schemas; BFF proxy `/api/core/similar`
- [ ] 4.3 Unit tests with a fake ES client; integration test with synthetic documents

## 5. UI

- [ ] 5.1 `SimilarPanel` with filters, outcome badges, empty/error states
- [ ] 5.2 Mount on lead card/detail, scout history, needs-review, profile items, conversation messages, search results
- [ ] 5.3 `/ops` embeddings coverage card + `GET /ops/embeddings/status`

## 6. Probable rewrites

- [ ] 6.1 Post-embed kNN (`author=other`, 0.95) and notice on read models
- [ ] 6.2 `copy_suggestions` storage and accept/reject endpoints when copy tables exist (audited)

## 7. Rollout

- [ ] 7.1 Deploy with hooks off; build v2; parity check; switch alias
- [ ] 7.2 Enable hooks; backfill dry run, then live; coverage ≥ 99%
- [ ] 7.3 Drop v1; update `lead-affinity-signal` tasks to depend on this change
- [ ] 7.4 Docs: CLAUDE.md, `docs/deploy.md` sizing (1 GB page cache + 4 GB disk per million vectors), operator note on `--ubatch-size`
