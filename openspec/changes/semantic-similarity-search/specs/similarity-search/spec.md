## ADDED Requirements

### Requirement: Similar content can be requested for any entity or text
`POST /similar` SHALL accept either a reference (`doc_type`, `entity_id`) or raw `text`, and return the nearest indexed documents by cosine similarity with their score, doc type, entity id, author, location, date, and a text excerpt. The source entity itself SHALL be excluded. `min_score` SHALL default to 0.80 and `limit` to 10. The response SHALL state `method` as `vector` or `text`.

#### Scenario: More like this lead
- **WHEN** the client requests similar documents for `lead_post:42`
- **THEN** the nearest documents other than `lead_post:42` are returned with cosine scores in descending order and `method="vector"`

#### Scenario: Raw text query
- **WHEN** the client posts a paragraph of text
- **THEN** the text is embedded once by the local embeddings endpoint and neighbours are returned

### Requirement: Similarity results are filterable
`POST /similar` SHALL accept `doc_types`, `author` (`same`, `other`, `any`; default `any`), `location`, `since`, `until`, `lead_status`, and `include_deleted` (default false), applied as kNN filters so that `limit` results satisfying the filters are returned when they exist. An accepted filter SHALL NOT be silently dropped.

#### Scenario: Only other authors
- **WHEN** the client requests neighbours of a lead post with `author="other"`
- **THEN** no returned document belongs to that lead's author

### Requirement: Similarity degrades visibly to text matching
When the source has no vector and cannot be embedded, `POST /similar` SHALL answer with a `more_like_this` text query over the same filters and return `method="text"`. It SHALL NOT return an empty list because of a missing vector alone.

#### Scenario: Source not yet embedded and endpoint down
- **WHEN** similar documents are requested for a just-indexed lead while the embeddings endpoint is unreachable
- **THEN** text-based neighbours are returned with `method="text"`

### Requirement: "More like this" is available where posts and messages are read
The web app SHALL offer a Similar action on lead cards, lead detail, scout history posts, needs-review items, profile items, conversation messages and global search results, opening a panel that lists neighbours with score, author, date, lead status, latest recommendation and effective human verdict, links to the owning page, filter controls for type and author, and empty and error states. The panel SHALL call `/api/core/similar`.

#### Scenario: Similar leads and what happened to them
- **WHEN** the user opens Similar on a needs-review post
- **THEN** the panel lists similar past leads with their status (ignored, contacted, engaged) and verdicts

### Requirement: Probable rewrites by other authors are suggested
After a post-like document (`lead_post`, `scout_post`, `profile_item` post) is embedded, the system SHALL look for documents by a different author at cosine 0.95 or above. Matches not already in the same copy cluster SHALL be shown on the post as "probable rewrite" and, when copy clusters exist, stored as a suggestion the user can accept (joining the posts into a cluster, audited) or reject. The system SHALL NOT create or merge a cluster from semantic similarity without that action.

#### Scenario: Reworded copy from another account
- **WHEN** account B posts a thorough rewording of account A's post that shares little exact wording but scores 0.96
- **THEN** B's post shows a probable-rewrite notice linking A's post, and a cluster suggestion awaits the user's decision
