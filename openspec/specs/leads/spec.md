# leads Specification

## Purpose
Leads are provider posts the user has saved as potential contacts. The capability covers saving posts as `lead_posts`, the lead status lifecycle, listing/filtering leads, lead detail with author context, initiating contact from a lead, and the guarantee that every saved lead's content is also persisted as a `profile_item` so analysis always has at least one item to work from.

## Requirements

### Requirement: Saving a lead persists the post and a profile item atomically

`POST /leads/save` SHALL create or upsert a `lead_posts` row (unique by `(provider_id, external_post_id)`) and, in the same database transaction, upsert a `profile_item` for the post linked to the author's `external_accounts` row (`item_type='post'`, keyed by `(account_id, item_type, external_item_id)`). The profile item's `text_content` is the post title and body combined, `subreddit` is the source location, `link_title` is the title, and `remote_visibility` is `visible`. The save response SHALL include the created `profile_item_id`.

#### Scenario: Save a lead with body text

- **WHEN** the client calls `POST /leads/save` with a post that has a title and body
- **THEN** a `lead_posts` row exists for the post
- **AND** a `profile_item` of type `post` exists for the author's account containing the combined title and body
- **AND** the response includes a non-null `profile_item_id`

#### Scenario: Re-saving the same post

- **WHEN** `POST /leads/save` is called again for an already-saved post
- **THEN** the existing `lead_posts` row and `profile_item` are updated in place, not duplicated

### Requirement: Lead status lifecycle

Each lead SHALL carry a status in `new`, `saved`, `ignored`, `contact_queued`, `contacted`, updated via `PATCH /leads/{lead_id}/status`. Status mutations SHALL write to the audit log.

#### Scenario: Marking a lead ignored

- **WHEN** the user updates a lead's status to `ignored`
- **THEN** the lead's status is `ignored`
- **AND** an audit log entry records the change

### Requirement: Lead listing supports status and source filters

`GET /leads` SHALL return leads with cursor pagination and support filtering by status and by `lead_source` (`manual` or `scout_watch`). List entries SHALL include author information (analysis state and available profile metadata) and, when present, the latest analysis recommendation and confidence so the list can badge leads.

#### Scenario: Filter to scout-watch leads

- **WHEN** the client calls `GET /leads?lead_source=scout_watch`
- **THEN** only leads created by scout watch runs are returned

### Requirement: Lead detail exposes post content and author context

`GET /leads/{lead_id}` SHALL return the lead's post content (title, body, source location, post URL, remote visibility) along with author account information, so the lead detail page can render the post together with the author's profile panel and analysis results.

#### Scenario: View a lead

- **WHEN** the user opens `/leads/<id>`
- **THEN** the post body and title are displayed
- **AND** the author's profile panel and any existing analysis are available on the same page

### Requirement: Contact can be initiated from a lead

`POST /conversations/initiate/from-lead/{lead_id}` SHALL start (or route to) a conversation with the lead's author. The flow SHALL check the `do_not_contact` list and block contact for listed usernames, and SHALL never send a message without an explicit user action.

#### Scenario: Contacting a lead's author

- **WHEN** the user triggers contact from a lead whose author is not on the do-not-contact list
- **THEN** an existing conversation with the author is opened if one exists, otherwise a compose flow for a new conversation is presented

#### Scenario: Author is on the do-not-contact list

- **WHEN** the user triggers contact for an author present in `do_not_contact`
- **THEN** the request is rejected and no conversation or message is created

### Requirement: Auto-analyze on save

After a successful save, the frontend SHALL trigger lead analysis fire-and-forget (`POST /leads/{id}/analyze`). Because the save already persisted the lead post as a profile item, the analysis pipeline SHALL find at least one profile item for the account and SHALL NOT report "no posts available" for a saved lead.

#### Scenario: Analysis right after save

- **WHEN** analysis starts immediately after `POST /leads/save` returns
- **THEN** at least the lead post itself is available to the analysis pipeline as a `profile_item`
