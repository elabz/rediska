## ADDED Requirements

### Requirement: The voice corpus is made of user-curated post and intro pairs
The system SHALL keep `voice_exemplars` linking one of the user's outgoing first messages to the text of the post it answered, with an outcome (`no_reply`, `replied`, `engaged`) and a mark (`unreviewed`, `exemplar`, `exclude`). The user SHALL be able to mark any of their own outgoing messages from the conversation view, and to confirm, replace, paste, or clear the linked post text on a corpus page. Only rows marked `exemplar` with post text SHALL be used as demonstrations for drafting or exported for training; exemplars without post text SHALL be used as style samples only. The corpus page SHALL also mark in bulk the first outgoing messages of all conversations in a chosen conversation list. An exemplar MAY be flagged `held_out`, which excludes it from retrieval and from dataset export so it can serve later engine comparisons. Every corpus mutation SHALL write `audit_log`.

#### Scenario: Marking an intro
- **WHEN** the user marks their first message in a conversation as an exemplar and confirms the proposed post
- **THEN** an exemplar with that message, that post text and the conversation's current outcome exists

#### Scenario: Intro without a recoverable post
- **WHEN** the user marks an intro as an exemplar and chooses "not a reply to a stored post"
- **THEN** the exemplar is stored without post text and is never used as a post→message demonstration

### Requirement: Past intros get proposed post links
A backfill SHALL propose, for each conversation opened by the user, the lead post by the same author with the latest post time before the first message, else the latest stored post by that author within 14 days before it, and store the proposal as `unreviewed`. It SHALL use the `jobs` ledger, default to a dry run reporting counts, and never mark anything `exemplar` by itself.

#### Scenario: Dry run
- **WHEN** the backfill runs with `dry_run=true`
- **THEN** it reports how many conversations would receive a proposal and writes nothing

### Requirement: Sent drafts feed the corpus with their edit distance
When the first outgoing message of a conversation with an `origin_lead_id` is sent, the system SHALL create an `unreviewed` exemplar carrying the post snapshot, and, when the message came from a draft, the normalised edit distance between the draft and the sent text. Outcomes SHALL update when a reply arrives or the account becomes engaged.

#### Scenario: Draft edited before sending
- **WHEN** the user changes a third of a draft and sends it
- **THEN** the exemplar records an edit ratio of about 0.33 and the message origin is `draft_edited`

### Requirement: Each identity has a fact sheet that bounds what a draft may claim
Each identity SHALL have a fact sheet of statements the drafter may make about the sender and a list of things never to say, editable on `/settings/voice`. Drafting SHALL be refused for an identity with an empty fact sheet.

#### Scenario: No fact sheet
- **WHEN** a draft is requested for an identity whose fact sheet is empty
- **THEN** the request fails with an explanatory error and no inference call is made

### Requirement: Drafts are generated locally from retrieved exemplars
`POST /leads/{id}/reply-draft` and automatic preparation SHALL build the prompt from the identity's fact sheet, the exemplars whose posts are most similar to the lead's post (preferring `replied` and `engaged`, avoiding near-identical exemplars), optional style samples, and the lead's post and analysis facts, and SHALL call only the locally configured inference endpoint through the inference gate. The draft SHALL store the engine, model, exemplar ids and full prompt. Post and message content SHALL be used verbatim with no filtering. Generation SHALL run as a Celery task with `jobs` idempotency.

#### Scenario: Draft for a lead
- **WHEN** the user requests a draft for a lead and at least one exemplar exists
- **THEN** a draft is stored with the exemplars used and shown on lead detail, and nothing is sent

#### Scenario: No exemplars yet
- **WHEN** a draft is requested and no paired exemplar exists
- **THEN** the draft is generated from the fact sheet and style samples only and is labelled low-confidence

### Requirement: Drafts are verified before they are sendable
Each draft SHALL pass deterministic checks (length within the user's typical band, no URL, no username other than the recipient's, no assistant boilerplate, cosine similarity below 0.90 to every intro sent in the previous 90 days, not a near-copy of a retrieved exemplar) and a local LLM verification that every claim about the sender is supported by the fact sheet and that the draft responds to at least one specific detail of the post. A draft failing any check SHALL be `needs_edit` and shown with the failed checks.

#### Scenario: Invented fact
- **WHEN** a draft says the sender lives in a city that is not in the fact sheet
- **THEN** the draft is `needs_edit` with the unsupported claim listed

#### Scenario: Repeats an earlier intro
- **WHEN** a draft scores 0.93 against an intro sent last week
- **THEN** the draft is `needs_edit` for repetition

### Requirement: A reply draft is a server-side record with a lifecycle
The system SHALL store each generated reply as a `reply_draft` bound to one lead and one identity, with body, engine, model, prompt, exemplars used, verification results, evaluated guards, trigger (`on_request`, `prepared`) and a status of `generating`, `ready`, `needs_edit`, `notified`, `opened`, `sent`, `rejected` or `expired`. At most one draft per lead and identity SHALL be live; regenerating SHALL supersede the previous one. Reply drafts SHALL be distinct from browser-side compose drafts. `GET /reply-drafts` SHALL list drafts with cursor pagination and status filter; reject SHALL require a reason. Every generate, regenerate, open, reject and expiry SHALL write `audit_log`. No reply-draft operation SHALL send a message.

#### Scenario: Using a draft
- **WHEN** the user chooses Use draft on a ready draft
- **THEN** the conversation is initiated from the lead, the compose box contains the draft text with the draft id attached, the draft is `opened`, and nothing has been sent

#### Scenario: Sending a used draft
- **WHEN** the user sends that compose text through the normal send action
- **THEN** the message records the draft id and origin, and the draft becomes `sent`

#### Scenario: Rejecting
- **WHEN** the user rejects a draft with reason "wrong tone"
- **THEN** the draft is `rejected` with that reason and the lead is not drafted again unless the user asks

### Requirement: Drafts that lost their purpose expire
A live draft SHALL become `expired` when its post is deleted or removed, its author is banned, any message has been sent to its author, or its lead leaves `new`/`saved`. Post age alone SHALL NOT expire a draft. Expired drafts SHALL be retained and SHALL leave the Drafts tab.

#### Scenario: Author banned while a draft waits
- **WHEN** the author of a lead with a `notified` draft is banned
- **THEN** the draft becomes `expired`

#### Scenario: Old post, never messaged
- **WHEN** a draft's post is three weeks old and the author has never been messaged
- **THEN** the draft stays live

### Requirement: Drafts are prepared automatically for high-match leads when the identity opts in
Each identity SHALL have `draft_mode` of `on_request` (default) or `prepare_and_notify`, changed only by an explicit audited user action. In `prepare_and_notify`, the system SHALL generate a draft for every lead for which one shared, pure guard function holds: recommendation `suitable`, priority `high`, all gates passed, compatibility at or above `DRAFT_MIN_COMPATIBILITY` (default 0.75), no disagreeing human evaluation, status `new` or `saved`, post visible; author not banned, no message ever sent to the author, not in a ring-suspect or confirmed-ring copy cluster, account not deleted or suspended; location without a contact restriction; identity with a non-empty fact sheet. There SHALL be no daily limit on prepared drafts and no post-age limit. Guards whose capability is not deployed SHALL be recorded as `not_available` on the draft. Generation SHALL run through the inference gate behind lead analysis and SHALL be idempotent per lead and identity.

#### Scenario: High-match lead arrives
- **WHEN** an identity is in `prepare_and_notify` and an eligible lead is created
- **THEN** a verified draft with trigger `prepared` is generated for it and no message is sent

#### Scenario: Ring suspect
- **WHEN** an otherwise eligible lead's post belongs to a ring-suspect copy cluster
- **THEN** no draft is prepared automatically and the reason is available on request

#### Scenario: Author already messaged
- **WHEN** an eligible lead's author has received any message from the user
- **THEN** no draft is prepared

#### Scenario: Burst of leads
- **WHEN** thirty eligible leads arrive in one hour
- **THEN** thirty drafts are generated in turn behind running analyses, none is skipped for a quota, and no lead gets two drafts

### Requirement: A draft can be requested by hand for any lead
A Draft action SHALL be available on lead detail and lead cards for any lead regardless of how it was found or how it scored, and a Save and draft action SHALL be available on Browse posts and needs-review items, which SHALL first create the lead through the existing save or promote path. A manual request SHALL be refused only when the author is banned or the identity has no fact sheet; every other unmet guard SHALL be stored on the draft and shown as a warning. Manual drafts SHALL NOT send a notification.

#### Scenario: Lead saved by hand with a low score
- **WHEN** the user presses Draft on a manually saved lead whose recommendation is `needs_review`
- **THEN** a draft is generated and shown with a warning listing the unmet match guards

#### Scenario: Save and draft from Browse
- **WHEN** the user presses Save and draft on a Browse post
- **THEN** the post is saved as a lead and a draft for it is generated

#### Scenario: Banned author
- **WHEN** the user presses Draft for a lead whose author is banned
- **THEN** the request is refused with the ban shown

### Requirement: The draft subject is the post title
Where the provider's first message has a subject, the draft's subject SHALL be the title of the post being answered, truncated to the provider's length limit, and SHALL NOT be generated by the model. The user MAY edit it before sending.

#### Scenario: Reddit private message
- **WHEN** a draft is created for a lead whose post title is 140 characters long
- **THEN** the draft subject is that title cut to the provider's limit

### Requirement: The user is notified that drafts are waiting
When a prepared draft reaches `ready` or `needs_edit`, the system SHALL immediately send one `draft_waiting` notification for it through the `notifications` capability and mark the draft `notified` once delivered. The Leads page SHALL provide a Drafts tab with a count badge listing live drafts with lead priority, compatibility, draft status and age, with empty and error states; lead detail SHALL show the lead's draft with its failed checks, the exemplars used, Use draft, Regenerate and Reject.

#### Scenario: Opening from the notification link
- **WHEN** the user follows the link of a notification on the LAN or VPN
- **THEN** lead detail opens with the draft panel expanded

### Requirement: Drafting trust is measured from use
The system SHALL report per identity and engine: drafts generated, sent unchanged, sent edited with the median edit ratio, rejected by reason, expired, and reply rate by message origin with counts, over selectable periods, on `/ops`.

#### Scenario: Thirty drafts later
- **WHEN** 30 drafts have been sent
- **THEN** the metrics card shows the share sent unchanged, the median edit ratio, and reply rates for manual, edited and unchanged messages with their counts
