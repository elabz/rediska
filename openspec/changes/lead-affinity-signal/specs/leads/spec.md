## ADDED Requirements

### Requirement: Leads expose affinity and can be sorted by it

Lead list entries and lead detail SHALL include the stored affinity score, its reason when null, whether it is stale, and on detail the explanation exemplars. `GET /leads` SHALL accept `sort=affinity`, ordering by affinity descending with nulls last and then recency, combined with all existing filters. The default ordering SHALL remain priority tier then recency. When the feature is disabled the fields SHALL be omitted and `sort=affinity` SHALL fall back to the default ordering.

#### Scenario: Sorting by affinity

- **WHEN** the user selects the affinity sort on the Leads page
- **THEN** leads with the highest affinity come first and leads without a score come last

#### Scenario: Default unchanged

- **WHEN** no sort is requested
- **THEN** ordering is priority tier then recency, exactly as before
