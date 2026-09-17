# external-listing-resolution Specification (delta)

## ADDED Requirements

### Requirement: Link-only posts from supported listing hosts are resolved to their About text

The system SHALL maintain a registry of supported external listing hosts (initially `weheartbdsm.com` listing pages matching `weheartbdsm.com/listings/<id>`). When an ingested post's body is link-only (empty, blank, or consisting solely of the post's own URL) and the post URL matches a registered host, the system SHALL fetch the listing page, extract the text of its About section, and store that text as the post's body — exactly as if it were the content of the corresponding Reddit post.

#### Scenario: r/bdsmpersonals link post is resolved

- **WHEN** browse, scout watch, lead saving, or post ingestion encounters a Reddit post with empty `selftext` whose URL is `https://weheartbdsm.com/listings/8980?from=reddit`
- **THEN** the system fetches the listing page and extracts the About section text
- **AND** that text is stored as the post's body in the corresponding records (`lead_posts.body_text`, `scout_watch_posts.post_body`, `profile_items.text_content`, browse feed response)
- **AND** the original listing URL remains available on the record (post URL / raw data)

#### Scenario: Unsupported host is left untouched

- **WHEN** a link-only post points to a host not present in the registry
- **THEN** no fetch is attempted and the post is stored with its original body

#### Scenario: Post with its own body is left untouched

- **WHEN** an ingested post has non-empty `selftext` that is not merely its own URL
- **THEN** no resolution is attempted and the Reddit body is stored as-is

### Requirement: Resolution completes before AI analysis runs

The system SHALL resolve listing content for a post **before** any AI analysis of that post is enqueued or executed. Analysis SHALL NOT run against a bare link when resolvable content exists.

#### Scenario: Auto-analyze on lead save sees resolved content

- **WHEN** the user saves a lead for a link-only post from a supported host (which triggers auto-analysis)
- **THEN** the listing content is resolved and persisted synchronously within the save operation, before the analysis request is issued
- **AND** the analysis context contains the resolved About text, not the bare link

#### Scenario: Scout watch pipeline sees resolved content

- **WHEN** a scout watch records a matching link-only post from a supported host with auto-analyze enabled
- **THEN** the post body is resolved and persisted before `scout.analyze_and_decide` is enqueued for that post

#### Scenario: Pre-existing link-only lead is resolved at analysis time

- **WHEN** analysis runs for a lead whose stored body is still link-only and whose URL matches a registered host (e.g. a lead saved before this capability existed)
- **THEN** the system attempts resolution once and persists the resolved text before assembling the agent context

### Requirement: Resolution is best-effort and never fails ingestion

The system SHALL treat listing resolution as best-effort: any fetch or parse failure results in the post being stored with its original (link-only) body, a logged warning, and normal continuation of ingestion and analysis. Resolution failures MUST NOT raise errors to callers or fail background tasks.

#### Scenario: Listing page is unreachable

- **WHEN** the listing fetch times out or returns a non-success status
- **THEN** the post is stored with its original body and processing continues
- **AND** no error is surfaced to the user or the task queue

#### Scenario: About section cannot be found

- **WHEN** the listing page is fetched but the parser cannot locate the About section
- **THEN** the post is stored with its original body and a warning is logged

### Requirement: Listing fetches are polite and cached

The system SHALL fetch listing pages with a bounded timeout and an identifying User-Agent, enforce a per-host rate limit via the existing Redis-backed rate limiter, and cache resolved results keyed by the canonical listing URL (tracking parameters stripped) so repeated encounters of the same listing do not re-fetch the page. Failed resolutions SHALL be negatively cached for a shorter period.

#### Scenario: Same listing encountered twice

- **WHEN** a listing URL that was resolved recently is encountered again (e.g. the same post appears in a subsequent scout run)
- **THEN** the cached About text is used and no new HTTP request is made to the listing host

#### Scenario: Burst of link-only posts

- **WHEN** a browse or scout run yields many unresolved listings at once
- **THEN** fetches are throttled by the per-host rate limit rather than issued unbounded
