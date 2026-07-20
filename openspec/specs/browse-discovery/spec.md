# browse-discovery Specification

## Purpose
Browse-discovery lets the user explore posts from a provider location (e.g. a subreddit) directly inside Rediska, filter and search them, and act on individual posts (save as lead, star the author, open the author's profile). It also opportunistically accumulates post content as `profile_items` for authors the system already knows, so later analysis has material to work with even when the author's public profile hides their posts.

## Requirements

### Requirement: Browse feed serves posts from a provider location

The core API SHALL expose `GET /sources/{provider_id}/locations/{location}/posts` returning posts from the named provider location, supporting a sort parameter (`hot`, `new`, `top`, `rising`, `controversial`), a time-filter parameter for time-windowed sorts, and an optional search query. Fetching from the provider SHALL go through the provider adapter (`browse_location`) and respect the provider rate limiter.

#### Scenario: Browse a subreddit sorted by new

- **WHEN** the client calls `GET /sources/reddit/locations/<subreddit>/posts?sort=new`
- **THEN** the response contains posts from that subreddit in the requested sort order
- **AND** each post includes its external id, title, body text, author username, and creation time

#### Scenario: Search query narrows the feed

- **WHEN** the client passes a non-empty search query parameter
- **THEN** only posts matching the query per the provider's search semantics are returned

### Requirement: Browse page offers preset search queries

The Browse page SHALL offer user-selectable preset search queries (e.g. `F4M OR F4A` combined with location terms) alongside a free-form query input, so recurring searches do not need retyping.

#### Scenario: Selecting a preset

- **WHEN** the user selects a preset query on the Browse page
- **THEN** the feed reloads using that preset as the active search query

### Requirement: Post cards support save-to-leads and author actions

Each post card in the Browse feed SHALL provide actions to save the post as a lead, star the author, and open the author's `UserProfilePanel`, without leaving the Browse page.

#### Scenario: Saving a post as a lead from Browse

- **WHEN** the user clicks "Save Lead" on a post card
- **THEN** the post is saved via the leads capability (`POST /leads/save`)
- **AND** the card reflects the saved state

### Requirement: Browse results are ingested as profile items for known authors

After the Browse page loads a batch of posts, the frontend SHALL fire a background `POST /profile-items/ingest-browse-posts` with the batch. For each post whose author already has an `external_accounts` row for the given provider, the backend SHALL upsert a `profile_item` (`item_type='post'`, keyed by `(account_id, item_type, external_item_id)`) from the post content; posts by unknown authors SHALL be skipped. The response SHALL report ingested/new counts and the list of `known_authors` so the UI can badge posts from already-known accounts.

#### Scenario: Batch contains a known author

- **WHEN** `POST /profile-items/ingest-browse-posts` receives a post whose `author_username` matches an existing external account for the provider
- **THEN** a `profile_item` for that post is created or updated for that account
- **AND** the author's username appears in `known_authors` in the response

#### Scenario: Batch contains only unknown authors

- **WHEN** every post in the batch has an author with no `external_accounts` row
- **THEN** no `profile_items` are created
- **AND** `known_authors` is empty

### Requirement: Background browse ingestion task

The system SHALL provide an `ingest.browse_location` Celery task that browses a provider location asynchronously, using the `jobs` ledger for idempotency and the standard retry policy.

#### Scenario: Browse task is idempotent

- **WHEN** `ingest.browse_location` is enqueued twice with the same payload while the first run is incomplete
- **THEN** the duplicate is deduplicated via the `jobs` ledger rather than executed twice
