## ADDED Requirements

### Requirement: Terms are lexically normalised before matching

Before any comparison, extracted terms and profile labels and aliases SHALL pass through the same normalisation: lowercase, trim, collapse whitespace, strip surrounding punctuation and leading `#`, split joined hashtags against the known vocabulary of labels and aliases, fold simple plurals and `-ing`/`-ed` suffixes, and strip leading stop-phrases such as "into", "love", "really enjoy", "big fan of". Normalisation SHALL be deterministic and SHALL NOT drop or alter the stored original wording.

#### Scenario: Joined hashtag

- **WHEN** the agent extracts "#ropebondage" and the profile has an interest "rope bondage"
- **THEN** the term matches that interest by label and the original wording "#ropebondage" is kept for display

#### Scenario: Stop-phrase

- **WHEN** the agent extracts "really into hiking"
- **THEN** it normalises to "hiking" and matches the "hiking" interest

### Requirement: Unmatched terms are matched semantically against the profile

A normalised term with no label or alias match SHALL be compared by cosine similarity between its embedding and the embeddings of every profile interest label and alias, using the configured local embeddings endpoint. When the best similarity is at or above the profile's `semantic_threshold` (default 0.82) and the pair is not a stored negative pair, the term SHALL count as a match for that interest with method `semantic` and the similarity recorded. A semantic match SHALL contribute the interest's full weight to the compatibility score and SHALL count once per interest regardless of how many terms matched it. Vectors SHALL be cached by normalised text and embeddings model name so that each distinct text is embedded at most once per model. Semantic matching SHALL NOT be used by any gate.

#### Scenario: Variant wording matches

- **WHEN** the agent extracts "being tied up", no alias covers it, and its similarity to "rope bondage" is 0.86
- **THEN** "rope bondage" is reported as matched with method `semantic`, similarity 0.86, and the original wording

#### Scenario: Below threshold

- **WHEN** the best similarity for a term is 0.74
- **THEN** the term is unmatched and recorded as such

#### Scenario: Rejected pair never matches

- **WHEN** the user has rejected the pair ("pet play", "petting zoo volunteering") and that term is extracted again
- **THEN** it does not match that interest regardless of similarity

#### Scenario: Deal-breakers are never matched semantically

- **WHEN** the deal-breaker gate is enabled and an extracted term is only semantically close to a deal-breaker
- **THEN** the gate does not fail on it

### Requirement: Matching degrades to exact when embeddings are unavailable

When the embeddings endpoint errors or times out, matching SHALL proceed with label and alias matches only, the analysis SHALL complete, and the preferences result SHALL record that semantic matching was skipped. The failure SHALL be logged and SHALL NOT be retried inside the analysis.

#### Scenario: Embeddings endpoint down

- **WHEN** the embeddings endpoint is unreachable during an analysis
- **THEN** the analysis completes with exact matches only and the result carries `semantic_matching: "skipped"`

### Requirement: Extracted terms accumulate in a vocabulary

Every extracted hobby and kink term SHALL be upserted into `interest_terms` keyed by normalised term, incrementing its occurrence count and updating last-seen, and recording its current resolution: `label`, `alias`, `semantic` (with interest and similarity), `unmatched`, or `ignored`. Terms SHALL be stored verbatim in their normalised and an example original form, with no content filtering. A backfill task SHALL be able to seed the vocabulary from stored preferences outputs, using the `jobs` ledger and defaulting to a dry run that reports counts.

#### Scenario: Frequent unmatched term becomes visible

- **WHEN** "primal" has been extracted from forty posts and matches nothing
- **THEN** the vocabulary lists it as unmatched with a count of forty

#### Scenario: Backfill dry run

- **WHEN** the backfill runs without `dry_run=false`
- **THEN** it reports how many terms and occurrences it would record and writes nothing

### Requirement: The user confirms, rejects, maps, or ignores terms

`GET /match-profile/vocabulary` SHALL list terms filterable by resolution and sortable by count, with cursor pagination. The user SHALL be able to: confirm a semantic match (the term becomes an alias of that interest in a new profile version), reject it (a negative pair is stored in a new profile version), map an unmatched term to an existing interest, create a new interest from a term, or mark a term ignored so it no longer appears as unmatched. Each action SHALL write `audit_log`. Actions that change the profile SHALL go through the normal profile save path so versioning, validation, and preview apply.

#### Scenario: Confirm turns semantic into alias

- **WHEN** the user confirms "being tied up" → "rope bondage"
- **THEN** a new profile version lists it as an alias, later occurrences match with method `alias`, and an audit row records the action

#### Scenario: Create interest from a term

- **WHEN** the user creates an interest from the unmatched term "primal" with a weight
- **THEN** a new profile version contains the interest and the term's resolution becomes `label`

### Requirement: Vocabulary tab and match explanations

The match profile page SHALL have a Vocabulary tab showing terms, counts, resolution, similarity for semantic matches, and the actions above, with loading, empty, and error states. Matched-interest chips on lead list and detail SHALL indicate the match method, and the detail view SHALL show the author's original wording for alias and semantic matches.

#### Scenario: Empty vocabulary

- **WHEN** no analysis has run since the feature was enabled and no backfill was done
- **THEN** the tab shows an empty state explaining that terms appear as posts are analysed and offers the backfill

#### Scenario: Semantic match explained on a lead

- **WHEN** a lead's compatibility includes a semantic match
- **THEN** the chip shows the interest, marks it as a semantic match, and reveals the original wording
