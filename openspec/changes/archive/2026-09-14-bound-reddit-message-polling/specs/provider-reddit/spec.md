## ADDED Requirements

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
