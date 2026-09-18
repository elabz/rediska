# provider-reddit Specification

## Purpose
The core is provider-agnostic: all provider access goes through an abstract adapter interface with normalized DTOs, and Reddit is the only concrete provider in v1. This capability covers the adapter contract, the Reddit implementation, and provider rate limiting.

## Requirements

### Requirement: Provider-agnostic adapter interface

The core SHALL define an abstract `ProviderAdapter` with methods `list_conversations`, `list_messages`, `browse_location`, `fetch_post`, `fetch_profile`, `fetch_profile_items`, and `send_message`, returning normalized DTOs (`ProviderMessage`, `ProviderConversation`, `ProviderPost`, `ProviderProfile`, `ProviderProfileItem`, `SendMessageResult`, `PaginatedResult`) with shared enums for direction, remote visibility, and profile item type.

#### Scenario: Core services consume only the interface

- **WHEN** a domain service (ingest, browse, send, analysis) needs provider data
- **THEN** it calls the `ProviderAdapter` interface and receives normalized DTOs
- **AND** no provider-specific response shapes leak into core domain models

### Requirement: Provider naming is confined to the provider module

The string "reddit" SHALL appear only inside the provider module (`providers/reddit/`) and provider-specific endpoints (e.g. `/providers/reddit/oauth/*`); core tables and services SHALL reference providers via `provider_id` and `external_*` columns.

#### Scenario: Adding a second provider

- **WHEN** a new provider is added
- **THEN** it requires a new module under `providers/` and a `providers` table row, with no schema changes to core tables

### Requirement: Reddit adapter implements the full surface with token auto-refresh

`RedditAdapter` SHALL implement the adapter interface against Reddit's API using OAuth tokens from `provider_credentials`, automatically refreshing expired access tokens. It SHALL additionally support inbox fetching, user post/comment fetching, remote message deletion (`delete_message`), and attachment extraction from message bodies.

#### Scenario: Expired access token is refreshed transparently

- **WHEN** an API request fails due to an expired access token
- **THEN** the adapter refreshes the token using the stored refresh token, re-stores it encrypted, and retries the request

#### Scenario: Remote delete goes through the adapter

- **WHEN** the user requests remote deletion of a sent message
- **THEN** the adapter calls Reddit's delete endpoint for that message's external id
- **AND** the local message record is preserved (only visibility/status is updated)

### Requirement: Profile fetch limits for automated pipelines

Automated analysis paths (Scout Watch) SHALL fetch bounded profile data via `fetch_profile_items_with_limit`, capped at 20 posts and 100 comments per user, to bound LLM context and provider load.

#### Scenario: Scout analysis fetches a bounded profile

- **WHEN** a Scout Watch pipeline analyzes a post author
- **THEN** at most 20 posts and 100 comments are fetched for that user

### Requirement: Redis-backed provider rate limiting

Provider calls SHALL be rate limited through a Redis-backed limiter configured by `PROVIDER_RATE_QPM_DEFAULT` (queries per minute), `PROVIDER_RATE_CONCURRENCY_DEFAULT`, and `PROVIDER_RATE_BURST_FACTOR`.

#### Scenario: QPM budget exhausted

- **WHEN** the per-minute request budget for a provider is exhausted (beyond the burst allowance)
- **THEN** further calls raise a rate-limit exceeded condition and are retried or deferred rather than sent
- **AND** concurrency above the configured limit is queued

### Requirement: Reddit adapter paces requests by the reported quota

The Reddit adapter SHALL read `X-Ratelimit-Remaining` and `X-Ratelimit-Reset` from every API response. When fewer than 10 requests remain in the current window, it SHALL delay each request so the remaining requests are spread evenly over the time left in that window, pausing no more than 30 seconds per request. It SHALL NOT pause once the reported window has ended. On HTTP 429 it SHALL wait (at most 30 seconds) and retry once, then return the response to the caller.

Requests made through one adapter on one event loop SHALL share a single HTTP client, which the caller can close.

#### Scenario: Quota running low

- **WHEN** a response reports 4 requests remaining and 40 seconds until reset
- **THEN** the next request is delayed by about 10 seconds

#### Scenario: Quota healthy

- **WHEN** responses report at least 10 requests remaining
- **THEN** requests are sent without delay

#### Scenario: Rate limited anyway

- **WHEN** Reddit responds with HTTP 429
- **THEN** the adapter waits and retries once, and returns the second response whatever its status

### Requirement: Provider adapter exposes location search and location info

The `ProviderAdapter` contract SHALL include `search_locations(query, limit)` returning normalized location summaries (name, title, description, member count, NSFW flag, created date) and `get_location_info(name)` returning the same summary plus the community's rules for one location, or `None` when it does not exist, is private, or is banned. The Reddit adapter SHALL implement both against the subreddit search, subreddit about, and subreddit rules endpoints (a rules fetch failure yields an empty rule list, not a failed lookup) using the identity's existing OAuth token, SHALL pace them through the same rate limiter and `X-Ratelimit-*` handling as other Reddit calls, and SHALL NOT filter results by NSFW status. Provider-specific naming SHALL stay inside the Reddit module; the core refers to "locations".

#### Scenario: Keyword search returns normalized locations

- **WHEN** the core calls `search_locations("rope personals", limit=25)` for a Reddit identity
- **THEN** the adapter returns up to 25 location summaries including NSFW communities, each with name, description, member count, and NSFW flag

#### Scenario: Unavailable location

- **WHEN** `get_location_info` is called for a private, banned, or nonexistent community
- **THEN** the adapter returns `None` and records the reason in the log without raising

#### Scenario: Rate limit is respected

- **WHEN** location lookups are issued while the Reddit rate-limit budget is nearly exhausted
- **THEN** the adapter delays the request according to the rate-limit headers rather than failing or bypassing the limiter
