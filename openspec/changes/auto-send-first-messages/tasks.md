## 0. Entry gate

- [ ] 0.1 Confirm from the `/ops` drafting metrics that at least one identity meets the unlock criteria; if not, stop — this change is not ready to apply

## 1. Schema and settings

- [ ] 1.1 Revision: `reply_drafts.send_after`, statuses `scheduled`/`cancelled`; identity auto-send limits and breaker state; `draft_mode` value `auto_send`; message origin `auto`
- [ ] 1.2 Settings `AUTO_SEND_ENABLED` (false), `AUTO_DAILY_CAP` (default 20, validated ≤ 20), `AUTO_HOLD_MINUTES`, `AUTO_MIN_COMPATIBILITY`, `AUTO_MAX_POST_AGE_HOURS`, `AUTO_UNLOCK_MIN_SENDS` in config, `.env.example`, compose blocks

## 2. Policy

- [ ] 2.1 `auto_send_policy.py`: unlock evaluation with per-criterion values, pacing (daily cap, optional quiet hours, no spacing; one automatic message per author ever), breaker triggers; pure functions, exhaustive unit tests
- [ ] 2.2 Mode change endpoint refuses with unmet criteria; audited; daily re-evaluation task

## 3. Scheduling and dispatch

- [ ] 3.1 Schedule eligible `ready` drafts with hold; queue the content-free notification
- [ ] 3.2 `voice.dispatch_auto_send` beat task: re-evaluate guards, provider visibility re-check, initiate via the shared service, enqueue `message.send_manual` with `origin=auto`, actor `agent` audit entry; `jobs` idempotency keyed on the draft; routing test
- [ ] 3.3 Cancel / Edit / Send now endpoints; audited
- [ ] 3.4 Breaker: trip, cancel scheduled sends, notify, manual reset; kill switch read at dispatch and send

## 4. Web

- [ ] 4.1 `/settings/voice`: mode ladder with live criteria values, caps, hold, quiet hours
- [ ] 4.2 Hold banner on lead detail; pending automatic sends on the dashboard; breaker notice; empty and error states

## 5. Tests and rollout

- [ ] 5.1 Integration tests on synthetic data: banned during hold, cap reached, `needs_edit` never scheduled, guard `not_available` blocks, breaker on 403, kill switch, replies never automatic
- [ ] 5.2 Update CLAUDE.md core principles and security wording, PRD principles
- [ ] 5.3 Deploy with the kill switch off; enable for one identity; review reply rates and breaker state after the first week
