# leads Specification (delta)

## ADDED Requirements

### Requirement: At most one active lead per author

The system SHALL maintain at most one active lead per `(provider_id, author account)`, where an active lead is one whose status is not `ignored` and which is not locally deleted. When a post is saved (manually or by scout promotion) for an author who already has an active lead, the system SHALL attach the post to that lead — upserting the post as a `profile_item`, refreshing the lead's `updated_at`, and returning the existing lead — instead of creating a new `lead_posts` row. The save response SHALL indicate that an existing lead was updated rather than created.

#### Scenario: Saving a second post by the same author

- **WHEN** `POST /leads/save` is called for a post whose author already has an active lead (saved from a different post)
- **THEN** no new `lead_posts` row is created
- **AND** the post is upserted as a `profile_item` for the author's account
- **AND** the response returns the existing lead, marked as attached/updated

#### Scenario: Author's only lead is ignored

- **WHEN** a save or promotion occurs for an author whose only lead has status `ignored`
- **THEN** the ignored lead is not resurrected and no new lead is created via automated paths
- **AND** an explicit manual add-to-leads action MAY override the ignored verdict

#### Scenario: Authorless post

- **WHEN** a post with no resolvable author account is saved
- **THEN** the existing per-post upsert semantics (keyed by `provider_id`, `external_post_id`) apply unchanged

### Requirement: Historical duplicate leads can be merged

A maintenance task SHALL merge pre-existing duplicate-author leads: grouping active leads by `(provider_id, author account)`, keeping the lead with the newest post as the survivor, repointing analysis history and scout-post linkage to the survivor, and soft-deleting the losers (`deleted_at`; never hard-deleting, per the data-preservation principle). The task SHALL default to a dry run that reports the merge plan without mutating, and every applied merge SHALL be audit-logged.

#### Scenario: Dry run reports without mutating

- **WHEN** the merge task runs with dry_run enabled
- **THEN** a report of merge groups (survivor and losers per author) is produced
- **AND** no rows are modified

#### Scenario: Applied merge preserves history

- **WHEN** the merge task runs with dry_run disabled for an author with three duplicate leads
- **THEN** one lead (newest post) survives, the other two are soft-deleted
- **AND** all `lead_analyses` and scout-post links point at the survivor
- **AND** an audit entry records the merge group
