## ADDED Requirements

### Requirement: Leads expose copies and prior knowledge of the same text
`GET /leads` items and `GET /leads/{id}` SHALL carry `copy` fields (cluster id, effective kind, distinct author count). Lead detail SHALL list the other authors of the same text with post time, account state, lead status, latest recommendation, effective human verdict, and links to their lead and profile. For `returning_author` clusters the earlier author's analysis SHALL be shown as context; it SHALL NOT change the lead's recommendation, priority, or status. `GET /leads` SHALL exclude leads whose post belongs to a handled spam ring unless `include_copies=true`; excluded leads are hidden, never deleted or changed. List queries SHALL remain batched per page.

#### Scenario: Spam-ring lead is hidden
- **WHEN** a saved lead's text belongs to a handled spam ring
- **THEN** the lead list and its count omit it, the lead keeps its status, and `include_copies=true` lists it again

#### Scenario: Lead written by a returning author
- **WHEN** the user opens a lead whose text was posted 60 days earlier by a now-deleted account that was `ignored`
- **THEN** lead detail shows that earlier account, its `ignored` status and its analysis, and the current lead's own analysis is unchanged

#### Scenario: Lead without copies
- **WHEN** a lead's fingerprint belongs to no cluster
- **THEN** `copy` is null and no badge is rendered
