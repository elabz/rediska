## ADDED Requirements

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
