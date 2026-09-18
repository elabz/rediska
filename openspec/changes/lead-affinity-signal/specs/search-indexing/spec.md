## ADDED Requirements

### Requirement: Lead posts are embedded

The embedding task SHALL support the `lead_post` document type: it SHALL build the text from the lead's title and resolved body, truncate it to the embeddings model's input limit, request a vector from the configured local embeddings endpoint, and store it on the lead's search document. A lead SHALL be embedded when it is saved or promoted and re-embedded when its body changes, including when a link-only body is later resolved. A backfill task SHALL embed existing leads in batches through the `jobs` ledger with a dry run by default. Embedding failures SHALL NOT fail saving or analysing a lead.

#### Scenario: New lead is embedded

- **WHEN** a lead is saved or auto-promoted
- **THEN** its search document gains an embedding and the lead becomes retrievable by vector search

#### Scenario: Backfill dry run

- **WHEN** the backfill runs without `dry_run=false`
- **THEN** it reports the number of leads lacking an embedding and writes nothing

#### Scenario: Resolved body triggers re-embedding

- **WHEN** a link-only lead's body is replaced by resolved listing text
- **THEN** the lead is embedded again from the resolved text
