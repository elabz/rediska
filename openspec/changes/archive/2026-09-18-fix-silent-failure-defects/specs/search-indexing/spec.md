## MODIFIED Requirements

### Requirement: Search results are filterable by document type and visibility

The search API SHALL accept a `doc_types` filter restricting results to any subset of `message`, `lead_post`, `profile`, and `conversation`. By default, documents whose remote visibility marks them deleted/removed SHALL be excluded; an explicit include-deleted flag SHALL allow callers to opt in to locally-hidden content.

A caller-supplied `exclude_visibility` list SHALL be applied to the executed query as a negative constraint: every document whose `remote_visibility` matches any listed value SHALL be absent from the results. A filter that the API accepts SHALL NOT be silently discarded — if a supplied filter cannot be applied, the request SHALL fail with an error rather than return a wider result set than the caller asked for.

Documents whose `remote_visibility` field is absent SHALL NOT be excluded by an `exclude_visibility` list, since absence does not indicate a matching visibility state.

#### Scenario: Filtering to one document type

- **WHEN** a client searches with `doc_types: ["lead_post"]`
- **THEN** every hit in the response has `doc_type` equal to `lead_post`

#### Scenario: Remote-deleted content excluded by default

- **WHEN** a client searches without an include-deleted flag
- **THEN** documents marked remote-deleted/removed or locally deleted are absent from the results

#### Scenario: Explicit visibility exclusion is applied

- **WHEN** a client searches with `exclude_visibility: ["removed", "deleted_by_author"]`
- **THEN** the query sent to the search engine carries a negative clause for those values
- **AND** no returned hit has a `remote_visibility` of `removed` or `deleted_by_author`

#### Scenario: Documents without a visibility field survive exclusion

- **WHEN** a client searches with a non-empty `exclude_visibility` list
- **AND** a matching document has no `remote_visibility` field
- **THEN** that document is still returned

#### Scenario: An unapplicable filter fails the request

- **WHEN** a client supplies a filter the search layer cannot apply
- **THEN** the request fails with an error
- **AND** no result set is returned that is wider than the filter requested
