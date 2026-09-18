## Context

Sources enter the system only when the user types a location into a scout watch. The user knows of no other source of similar ads, so the system has to propose them. Three facts make that feasible without new infrastructure:

- `profile_items.subreddit` already records where every analysed author posts.
- Verdicts, lead status, contact/engagement state, and human evaluations already say which authors were worth finding.
- Link-only posts already carry outbound URLs, and `external_listing.py` already has a host registry.

Constraints: local-only inference behind a concurrency gate of 1; Reddit rate limits shared with inbox sync; never online; no generic scraping; no autonomous action; agents and tasks must not read inbox content; `scout_watch_posts.watch_id` is NOT NULL with cascade delete.

## Goals / Non-Goals

**Goals:**
- Rank unseen communities by evidence that qualified authors use them.
- Let the user measure a candidate's real yield cheaply before watching it.
- Put existing watches and candidates on one comparable yield scale.
- Surface external listing sites worth a parser, without fetching them.

**Non-Goals:**
- Auto-watching, auto-promotion, non-Reddit providers, web search, scraping (see proposal).

## Decisions

**1. Lift over raw frequency.**
Ranking by raw count surfaces the big general communities every Reddit user posts in. Lift (share among qualified authors divided by share among all analysed authors) cancels popularity. A minimum of 3 distinct qualified authors guards against one prolific author creating a candidate. The community's qualified rate is shrunk toward the overall base rate by 10 pseudo-authors before dividing (changed after the first real run: with ~29% of analysed authors qualified, add-one smoothing let every 3-of-3 community hit the ~3.45 lift ceiling and fill the top of the list; with shrinkage 3 of 3 scores ~1.56 and 20 of 30 ~2.0). *Alternative:* embed community descriptions and rank by similarity to watched ones. Rejected as the primary signal: it measures topic, not whether the people the user wants are there. It can be added later as a tiebreak.

**2. "Qualified" is defined by existing signals, centralised in one function.**
`is_qualified_author()` lives in `source_discovery.py` and reads lead verdict, `contact_state`/`engagement_state`, and effective evaluations. When the match-profile change lands, only this function changes. Engaged and contacted authors are counted even if the agent said `needs_review`, because the human's action outranks the agent.

**3. Mining is pure SQL plus Python over metadata, daily.**
Two grouped queries (location by qualified authors, location by all analysed authors) and one pass over outbound URLs. No provider calls, no LLM. It reads community names, URL hosts, and verdicts only, never message or inbox tables. Location info (size, description) is fetched lazily when a candidate is first displayed and cached on the row, so mining never spends rate-limit budget.

**4. A trial is a hidden, never-scheduled scout watch.**
`scout_watches.is_trial = true`, `is_active = false`. This reuses `record_post`, external-listing resolution, dedupe, the per-post pipeline, prior-verdict skips, evaluation controls, and history UI with no parallel code path, and satisfies the NOT NULL `watch_id`. `run_all_watches` ignores inactive watches already; the watch list, needs-review queue, and calibration report filter `is_trial = false`. Auto-promotion is disabled by a guard in `analyze_and_decide`, not by setting `min_confidence` above 1, so the intent is explicit and testable. On accept, the trial watch is converted in place (`is_trial = false`, user settings applied, `is_active = true`), so its seen posts are not re-analysed. *Alternative:* nullable `trial_id` on posts with a nullable `watch_id`. Rejected: it touches every query that assumes a post has a watch.

**5. Trials are small, serial, and cancellable.**
Each post costs up to six sequential LLM calls, so 25 posts is on the order of an hour of inference. One trial at a time, cap 50, cancel between posts via the `jobs` ledger, same pattern as prompt replay. Trials run on the `scout` queue and share the inference gate, so live scout analysis is slowed, not starved. If the separate "demographics first, stop on hard fail" optimisation lands, trials get cheaper for free.

**6. Trial posts are exempt from the 3-day history cleanup until the candidate is resolved.**
Otherwise the evidence behind a yield report disappears before the user reads it. Cleanup skips posts whose watch `is_trial` and whose candidate is `new`/`trialled`/`snoozed`; after accept they follow normal retention, after dismiss they are detached per the existing "posts with analysis output are detached, never deleted" rule.

**7. External hosts are reported, never fetched.**
The registry rule "unregistered hosts are never fetched" stays absolute. The candidate carries count and example URLs so the user can look and decide whether a parser change is worth proposing.

**8. Provider contract grows by two read-only methods.**
`search_locations` and `get_location_info` on `ProviderAdapter`, with a normalized `ProviderLocation` DTO. Default implementation raises `NotImplementedError` so future providers opt in. Reddit's implementation goes through the existing rate limiter.

**9. Link-only sightings are recorded as metadata (added during implementation).**
Scout posts do not store their URL, and a link-only post whose host is unregistered is skipped for its empty body *before* `record_post`, so the host tally had no scout input. Scout runs, trials, and `/browse` now record such URLs in `source_link_sightings` (provider, post id, host, canonical URL, source, seen-at; unique per post). Registered and provider/media hosts are not recorded, nothing is fetched, and the rows survive the 3-day scout history retention so the tally covers the mining window. *Alternative:* record skipped posts in `scout_watch_posts`. Rejected: they would clutter watch history and be deleted after 3 days.

## Risks / Trade-offs

- [Lift is noisy with few qualified authors] → evidence floor, smoothing, counts shown next to the score, and the trial as the real test.
- [Candidates mirror past choices and never reach a truly new niche] → keyword search and manual candidates cover the cold-start path; outbound hosts give a second, independent signal.
- [Stored history is partial: only what was fetched per author] → lift compares like with like because both numerator and denominator use the same partial histories; documented as a known bias.
- [Trials compete with live analysis for the single inference slot] → serial, capped, cancellable; optional quiet-hours setting deferred.
- [Reddit rate budget shared with inbox sync] → location lookups are lazy, cached, and paced by the existing limiter.
- [A candidate community forbids the kind of contact the user intends] → location info shows the description; the decision stays with the human. No sending is involved in discovery.
- [Hidden trial watches leak into existing screens] → one shared query filter plus tests on the watch list, needs-review queue, calibration report, and beat scheduler.

## Migration Plan

1. Migration `020`: `source_candidates`, `source_trials`, `source_link_sightings`, `scout_watches.is_trial` (default false). Additive, reversible by downgrade.
2. Ship mining and the read-only Discover list first; verify candidates look sane on real data before enabling trials.
3. Ship trials and accept.
4. New env vars (`DISCOVERY_MIN_QUALIFIED_AUTHORS`, `DISCOVERY_TRIAL_SAMPLE`, `DISCOVERY_WINDOW_DAYS`) must be added to both `.env.example` and the `docker-compose.yml` environment blocks, or they have no effect.
Rollback: disable the beat entry and hide the tab; tables can stay.

## Open Questions

- Should authors the user marked `ignored` count as negative evidence (lowering lift for their communities), or only as part of the denominator? Proposed: denominator only for v1.
- Should a trial post that is `needs_review` optionally flow into the needs-review queue? Proposed: no by default, a per-trial toggle later.
- Window for mining: all history or trailing 180 days? Proposed: trailing 180 days so dead communities age out.
