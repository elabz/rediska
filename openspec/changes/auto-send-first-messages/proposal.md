## Why

`voice-matched-replies` makes the system prepare first messages and notify the user, who sends them. Once the numbers show that the user sends those drafts unchanged, the remaining click is pure delay on the leads where timing matters most. This change lets that click be skipped for a narrow class of leads, under caps and a cancellable hold, and takes itself back out of service at the first sign of trouble. It is deliberately a separate change: it amends the no-autosend safety rule, and it should only be applied when the draft metrics justify it.

## What Changes

- **BREAKING (safety rule): one bounded exception to no-autosend.** An identity's `draft_mode` gains a third value, `auto_send`. In that mode a prepared, fully verified draft for an eligible lead is scheduled to be sent after a hold window unless the user cancels. Everything else — replies, messages in existing conversations, identities in other modes — still needs an explicit send.
- **Earned, not configured.** `auto_send` can be selected only when the identity has at least `AUTO_UNLOCK_MIN_SENDS` (30) sent drafts, a median edit ratio ≤ 0.15 and ≥ 60% sent unchanged over the last 30, the contact ban list and copy detection are deployed, and the global `AUTO_SEND_ENABLED` switch is on. The refusal lists the unmet criteria.
- **Hold window with notification.** Scheduling sends the same content-free Slack notification ("a message will be sent at 14:32", link to the lead). Lead detail and the dashboard show Cancel, Edit and Send now. Guards are evaluated again at send time.
- **Stricter guards than drafting.** The shared guard function from `voice-matched-replies` with tighter thresholds (compatibility ≥ 0.8, post ≤ 48 h), draft status `ready` only (never `needs_edit`), plus a daily cap of 20 per identity (default and hard maximum) and optional quiet hours. There is no minimum spacing between automatic sends: each lead's author receives exactly one message, so there is nothing to cool down between; the provider's own rate limiter still applies.
- **Circuit breaker.** Any failed automatic send, a provider rate-limit or forbidden response, a restricted identity, a reply rate for automatic sends below half the manual baseline (from 20 sends), or three consecutive cancelled holds returns the identity to `prepare_and_notify`, cancels scheduled sends, and notifies.
- **Attribution.** Automatic sends use the existing `message.send_manual` path (`max_retries=0`), record `origin=auto`, and write `audit_log` with actor `agent` and the guards evaluated.

## Non-goals

- No automatic replies after the first message, ever.
- No cloud models, no content in notifications, no inbound integrations.
- No volume: the hard cap is 20 per day per identity, and only first messages.
- No content filtering.

## Capabilities

### New Capabilities
- `auto-send`: unlock criteria, scheduling and hold window, send-time re-evaluation, pacing, circuit breaker, kill switch.

### Modified Capabilities
- `messaging`: **BREAKING** — the no-autosend requirement names the bounded exception; message origin gains `auto`.
- `research-content-policy`: the human-control safety requirement names the exception instead of being silently contradicted.

## Impact

- **DB**: `reply_drafts.send_after`, `scheduled`/`cancelled` statuses; `identities` auto-send limits and breaker state.
- **Core/Worker**: `auto_send_policy.py` (unlock, pacing, breaker) on top of `reply_draft_policy`; `voice.dispatch_auto_send` beat task; conversation initiation through the shared service.
- **Web**: mode switch with criteria display on `/settings/voice`; hold banner on lead detail; pending sends on the dashboard; breaker notice.
- **Settings**: `AUTO_SEND_ENABLED` (false), `AUTO_DAILY_CAP`, `AUTO_HOLD_MINUTES`, `AUTO_MIN_COMPATIBILITY`, `AUTO_MAX_POST_AGE_HOURS`, `AUTO_UNLOCK_MIN_SENDS` — `.env.example` and compose blocks.
- **Docs**: CLAUDE.md core principle and security wording, PRD principles.
- **Depends on**: `voice-matched-replies`, `contact-ban-list`, `post-fingerprint-dedupe`, `semantic-similarity-search`. **Do not apply before the draft metrics meet the unlock criteria.**
