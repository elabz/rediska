## Context

After `voice-matched-replies`, the system has reply drafts with a lifecycle, a pure guard function (`reply_draft_policy.evaluate`), content-free notifications, message origin tracking, and per-identity metrics (edit ratio, share sent unchanged, reply rate by origin). Sending is `POST /conversations/{id}/messages` → `message.send_manual` (`max_retries=0`). No-autosend is a named safety control in `messaging`, `research-content-policy`, CLAUDE.md and the PRD. The Reddit account is the scarcest asset in the system; automated first contact is the activity most likely to get it restricted.

## Goals / Non-Goals

**Goals:** remove the click only where the evidence says the click adds nothing; keep a human able to stop any message until the moment it leaves; fail towards manual.

**Non-Goals:** throughput, multi-turn automation, any new drafting capability.

## Decisions

**1. A third value of `draft_mode`, not a new switch.** `on_request → prepare_and_notify → auto_send` is one ordered ladder; every lower level's behaviour stays on (drafts are still listed and notified).

**2. Unlock is computed, shown, and re-checked.** Criteria: ≥ 30 sent drafts; over the last 30, median edit ratio ≤ 0.15 and ≥ 60% `draft_as_is`; ban list and copy detection deployed; `AUTO_SEND_ENABLED=true`. The settings page shows each criterion with its current value. Criteria are re-checked daily; falling below them trips the breaker. *Alternative considered:* a blind "which is yours" test — useful for comparing engines, but the user's own sending behaviour is the more direct evidence.

**3. Hold window is the human-in-the-loop.** `scheduled` drafts carry `send_after = now + AUTO_HOLD_MINUTES` (default 30). Scheduling emits the standard content-free notification. Cancel → `cancelled` (lead not rescheduled); Edit → draft returns to the manual path; Send now → explicit user send. *Alternative:* immediate send — rejected.

**4. Guards twice.** At scheduling and again inside `voice.dispatch_auto_send` immediately before initiating: shared guard function with `AUTO_MIN_COMPATIBILITY` (0.8) and `AUTO_MAX_POST_AGE_HOURS` (48), draft `ready`, every guard capability available (a `not_available` guard blocks auto-send, unlike drafting), pacing, breaker closed, kill switch on. A remote visibility re-check of the post is made through the provider's rate limiter before sending.

**5. Pacing: a cap, no cool-down.** `AUTO_DAILY_CAP` default 20, validated ≤ 20 (user decision). No minimum spacing or jitter between sends (user decision): one message per lead means no recipient is ever messaged twice, and sends already pass through the provider rate limiter that paces all Reddit calls from `X-Ratelimit-*` headers. Optional quiet hours. Leads beyond the cap stay as notified drafts. In practice volume is bounded by supply: about 1–2 `suitable` leads a day today, about 15 if every post is read.

**6. One send path.** Dispatch calls the same initiation service as the manual route (ban check included) and enqueues `message.send_manual` with `origin=auto`. At-most-once is inherited; an ambiguous failure is a failure and trips the breaker.

**7. Breaker fails towards manual.** Triggers listed in the proposal. Tripping sets `draft_mode=prepare_and_notify`, cancels `scheduled` drafts back to `notified`, audits, notifies. Reset is a manual, audited action that re-evaluates the unlock criteria.

**8. Kill switch is read at dispatch and at send.** `AUTO_SEND_ENABLED=false` makes `auto_send` behave as `prepare_and_notify` without touching stored settings.

## Risks / Trade-offs

- [Account restriction for automated messaging] → accepted trade-off of removing the spacing: several first messages may leave within minutes when leads arrive together, which is the pattern Reddit's spam heuristics look for. Mitigations that remain: every message is individually written, the repetition check (cosine < 0.90 against sent intros) inherited from drafting, no links, restricted locations excluded, the 20/day cap, and the breaker on the first provider complaint. If the breaker ever trips on a rate-limit or forbidden response, reintroducing spacing is the first thing to try.
- [A wrong message cannot be unsent] → hold window, guards twice, first messages only; remote delete remains.
- [Weakening a named safety control] → narrow, opt-in, default off, earned from evidence, specified in the same requirement that states the rule, fully attributable.
- [Metric gaming by habit (user clicks send without reading)] → reply-rate breaker compares automatic sends with the manual baseline.
- [Notification missed during the hold] → hold length is the user's setting; quiet hours block scheduling, not just notifying.

## Migration Plan

Ship with `AUTO_SEND_ENABLED=false`. Enable for one identity; the cap is 20 from the start (user decision), and supply keeps real volume far below it at first. Rollback: kill switch.

## Resolved with the user (2026-09-18)

- "No cool-down" removes the spacing between sends. The cancellable hold before each send stays at 30 minutes, configurable down to 0.
- Drafting has no post-age limit; automatic sending keeps `AUTO_MAX_POST_AGE_HOURS` (48, configurable, 0 = none).
- Cap: 20 per day per identity, default and maximum.
