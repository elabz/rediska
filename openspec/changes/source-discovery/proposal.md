## Why

Every lead today comes from a location the user already knew about and typed into a scout watch. There is no mechanism that answers "where else do people like my good leads post?", so the funnel is capped by the user's own knowledge of Reddit and of external listing sites. The system already holds the evidence needed to answer it: the stored post history of every analysed author records which other communities they post in, and link-only posts record which external sites host listings.

## What Changes

- **Candidate sources mined from existing data (no new fetching).** A periodic task aggregates `profile_items.subreddit` across authors, comparing how often a community appears among *qualified* authors (lead verdict `suitable`, or contacted/engaged, or a human `agree` on a suitable verdict) against all analysed authors. Communities that are over-represented among qualified authors, are not already watched, and clear a minimum-evidence floor become **source candidates** with a lift score and the supporting counts.
- **External host candidates.** The same task tallies hosts of outbound URLs on link-only posts and in qualified authors' items. Hosts that recur and are not in the external-listing registry become candidates of kind `external_host`. They are surfaced as "worth writing a parser for"; the system never fetches an unregistered host.
- **Provider-side lookup.** A new provider capability, `search_locations(query)` and `get_location_info(name)`, lets the user search for communities by keyword and shows size, activity, description, and NSFW flag on a candidate. Reddit implements it; the core stays provider-agnostic.
- **Trial run before commitment.** A candidate can be given a bounded trial: fetch a small sample of recent posts and run them through the normal scout analysis pipeline, recorded as a trial, never auto-promoting leads. The result is a yield report (posts seen, empty/link-only, suitable / needs_review / not_recommended, top failing gate).
- **Human decides.** A "Discover" tab on `/settings/scout-watches` lists candidates with evidence and trial yield, with actions: run trial, create watch (pre-filled), dismiss, snooze. Dismissed candidates stay dismissed. Nothing is ever watched automatically.
- **Source yield on existing watches.** The same yield metrics are shown per existing watch, so low-yield watches are visible and the comparison with candidates is like for like.
- All mutating actions (trial, dismiss, snooze, create-from-candidate) write `audit_log`; the mining and trial tasks use the `jobs` ledger.

## Non-goals

- No automatic watch creation, no automatic lead promotion from trials, and no change to `min_confidence` or gate behaviour.
- No generic web scraping and no fetching of unregistered external hosts. Writing a parser for a newly discovered host is a separate change under `external-listing-resolution`.
- No new provider. Discovery of non-Reddit platforms beyond tallying outbound hosts is out of scope.
- No cloud APIs or web search services; discovery uses only stored data, the local LLM pipeline, and the provider API the identity is already authorised for.
- No content filtering of candidates or of trial posts; content is handled verbatim per the research content policy.
- Not the configurable match profile. Discovery uses whatever "qualified" means under the current gates and will inherit the profile when that change lands.

## Capabilities

### New Capabilities

- `source-discovery`: mining candidate sources from stored author history and outbound links, candidate lifecycle (new / trialled / accepted / dismissed / snoozed), bounded trial runs with yield reports, per-watch yield metrics, and the Discover UI.

### Modified Capabilities

- `provider-reddit`: adds location search and location info to the provider adapter contract, implemented for Reddit with the existing rate limiting.

## Impact

- **Database**: migration `020` adding `source_candidates` (kind, provider, name/host, evidence JSON, lift, status, snooze-until, timestamps) and `source_trials` (candidate, status, sample size, yield JSON, job link). `scout_watches` gains an `is_trial` flag: a trial is backed by a hidden, never-scheduled watch so trial posts reuse the existing pipeline, dedupe, and evaluation controls unchanged, while being excluded from auto-promotion, the watch list, and the needs-review queue.
- **Core**: new `domain/services/source_discovery.py`, routes under `/source-candidates`, additions to `providers/base.py` and `providers/reddit/adapter.py`, yield fields on the scout-watch read model.
- **Worker**: `discovery.mine_candidates` (beat, daily) and `discovery.run_trial` on the `scout` queue, both in the `jobs` ledger; task routes and the routing test updated.
- **Web**: Discover tab on `/settings/scout-watches`, BFF proxies under `/api/core/source-candidates`, yield column on the watch list.
- **Load**: a trial costs the same per-post inference as a scout run and shares the inference gate, so trials are capped in size and run one at a time.
- **Privacy**: mining reads only `profile_items` metadata (community name, URL host) and lead/scout verdicts. It never reads inbox or message content.
