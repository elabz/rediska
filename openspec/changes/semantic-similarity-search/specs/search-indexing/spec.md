## ADDED Requirements

### Requirement: Every indexed document type is embedded
Successful indexing of a `message`, `lead_post`, `scout_post`, `profile_item` of type post, `account_comments` or `profile_snapshot` document SHALL enqueue `embed.generate_for_entity` for it, and that task SHALL implement every one of these types. Embedding failure SHALL NOT fail or roll back indexing. A beat task `embed.sweep_missing` SHALL periodically embed a bounded batch of documents whose vector is missing or whose `embedding_model` differs from the configured model. Re-indexing a document whose prepared text is unchanged SHALL NOT re-embed it.

#### Scenario: Saved lead becomes semantically searchable
- **WHEN** a lead is saved
- **THEN** a `lead_post:<id>` document is indexed and, once the embed task has run, carries a vector, `embedding_model` and `embedded_at`

#### Scenario: Embeddings endpoint is down during indexing
- **WHEN** indexing succeeds and the embed call fails
- **THEN** the document is text-searchable, has no vector, and is picked up by a later `embed.sweep_missing` run

#### Scenario: Model changed
- **WHEN** `EMBEDDINGS_MODEL` changes
- **THEN** kNN queries ignore vectors from the old model and the sweeper re-embeds those documents

### Requirement: An account's comments are embedded together
Comments SHALL NOT be embedded one by one. For each account with stored comments the system SHALL maintain one `account_comments:<account_id>` document whose text is the account's comments merged newest first, each prefixed by its community name, until `EMBED_MAX_CHARS` is reached, and SHALL embed that text as a single vector. When the account's comments exceed the limit, the most recent ones SHALL be the ones included. The document SHALL be rebuilt and re-embedded when new comments are stored for the account, and only when the merged text changed. Individual comments SHALL remain text-searchable as `profile_item` documents. Similarity results for an `account_comments` document SHALL link to the account's profile.

#### Scenario: Account with many short comments
- **WHEN** an account has 300 stored comments averaging 100 characters
- **THEN** one `account_comments` document exists for it holding the most recent comments up to the limit, with one vector, and no comment has a vector of its own

#### Scenario: New comments arrive
- **WHEN** a profile refresh stores ten new comments for the account
- **THEN** the merged document is rebuilt with the newest comments first and re-embedded

#### Scenario: Nothing changed
- **WHEN** a profile refresh stores no new comments
- **THEN** the merged document is not re-embedded

### Requirement: Lead posts and analysed scout posts are indexed
Saving a lead, promoting a scout post to a lead, and completing the analysis of a scout post SHALL enqueue `index.upsert_content`. Analysed scout posts SHALL be indexed as `scout_post`; posts that were skipped or never analysed SHALL NOT be indexed. When a scout post is promoted, its `scout_post` document SHALL be removed in favour of the `lead_post` document. The search API's `doc_types` filter SHALL accept `scout_post`.

#### Scenario: Promotion replaces the scout document
- **WHEN** an analysed scout post is added to leads
- **THEN** search returns one `lead_post` hit for it and no `scout_post` hit

### Requirement: Embedding text is prepared by one rule
The text to embed SHALL be the title, a blank line, and the resolved body with whitespace collapsed. Text of at most `EMBED_MAX_CHARS` (default 1,400) SHALL be embedded in one call. Longer text SHALL be split on paragraph boundaries into chunks within that limit, at most four chunks SHALL be embedded, and the normalised mean SHALL be stored as the document's single vector. No input longer than the limit SHALL be sent to the embeddings endpoint. Content SHALL be embedded verbatim with no filtering.

#### Scenario: Long post
- **WHEN** a 5,000-character post is embedded
- **THEN** no request exceeds 1,400 characters and the document ends with exactly one vector

### Requirement: Vectors are not stored in the document source
The content index SHALL exclude the `embedding` field from `_source`. The index SHALL be addressed through an alias so a new index version can be built from the database and switched atomically, and the previous version SHALL be kept until document counts per type match.

#### Scenario: Reindex to a new version
- **WHEN** `index.reindex_to_version` completes with matching per-type counts
- **THEN** the alias points at the new index and search keeps working throughout

### Requirement: Search reports whether semantic ranking was used
`POST /search` responses SHALL include `semantic_used` and, when false in `hybrid` mode, a `semantic_unavailable_reason`. `vector` mode SHALL return an error, not BM25 results, when the query cannot be embedded. The `/search` page SHALL offer the three modes and show a notice when semantic ranking was unavailable.

#### Scenario: Hybrid search with the embeddings endpoint down
- **WHEN** a hybrid search runs and the query cannot be embedded
- **THEN** BM25 results are returned with `semantic_used=false` and a reason, and the page shows the notice

### Requirement: Vector coverage is observable and backfillable
`GET /ops/embeddings/status` SHALL report, per document type, indexed count, embedded count, current model, embed queue depth and last error, and the `/ops` page SHALL show it. `embed.backfill` SHALL embed existing documents in batches, default to a dry run, use the `jobs` ledger, be cancellable between batches, limit its own concurrency with `EMBED_MAX_CONCURRENT`, and pause while the inference gate is saturated.

#### Scenario: Dry-run backfill
- **WHEN** `embed.backfill` runs with `dry_run=true`
- **THEN** it reports the number of documents per type it would embed and embeds none
