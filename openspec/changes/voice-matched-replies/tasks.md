## 1. Schema and settings

- [ ] 1.1 Alembic revision: `conversations.origin_lead_id`, `origin_post_snapshot`; `messages.origin`, `messages.draft_id`; `reply_drafts`; `voice_exemplars` (incl. `held_out`); `voice_fact_sheets`; `identities.draft_mode`, quiet hours; `notification_log`
- [ ] 1.2 Models and Pydantic schemas
- [ ] 1.3 Settings `SLACK_WEBHOOK_URL`, `NOTIFY_DETAIL`, `DRAFT_MIN_COMPATIBILITY` (0.75), `VOICE_MODEL` in `config.py`, `.env.example`, and the core/worker/beat compose environment blocks

## 2. Dataset export: intros mode

- [ ] 2.1 Prerequisite: `dataset-export-service-tests` is applied (the other four export changes are independent of this one)
- [ ] 2.2 `mode=intros` in `dataset_export.py`: confirmed paired exemplars, fact sheet as system, `min_outcome` via the shared `conversation_outcome()`, `identity_id`, `list_id`, held-out exclusion; audit entry records the mode
- [ ] 2.3 Export dialog on `/inbox`: mode switch; tests on synthetic exemplars

## 3. Linkage and corpus

- [ ] 3.1 `initiate/from-lead` writes origin lead + post snapshot; reuse leaves origin untouched; tests
- [ ] 3.2 `voice_corpus.py`: mark/unmark, bulk mark from a conversation list, link/replace/paste/clear post, held-out flag, outcome updater on reply and engagement, audit
- [ ] 3.3 Auto-exemplar on the first outgoing message with edit ratio; `messages.origin` and `draft_id` set in the send path
- [ ] 3.4 `voice.backfill_links` task (dry run default, `jobs` ledger, only IDs and timestamps in logs)
- [ ] 3.5 Routes `/voice/exemplars`, `/voice/fact-sheet`; BFF proxies
- [ ] 3.6 Web: mark control on own messages in the conversation view; `/settings/voice` corpus tab (post and intro side by side; confirm / pick / paste / none; filters; counts) and fact sheet editor; empty and error states

## 4. Drafting

- [ ] 4.1 `voice_reply.py`: exemplar retrieval through the similarity service (reply bonus, diversity rule, held-out exclusion), prompt assembly, two candidates
- [ ] 4.2 Deterministic checks incl. repetition (cosine vs intros sent in 90 days) and exemplar near-copy (shingle Jaccard)
- [ ] 4.3 LLM verifier (claims vs fact sheet, specific detail), strict JSON parsing, fail-closed to `needs_edit`
- [ ] 4.4 `voice.generate_draft` task (queue `agent`, inference gate behind analysis, `jobs` idempotency, retry policy)
- [ ] 4.5 Unit tests with a fake inference client and synthetic exemplars; remove or replace `draft_intro.py` in step with `remove-dead-weight`

## 5. Reply drafts

- [ ] 5.1 `reply_drafts` lifecycle service: generate, supersede, open, resolve on send, reject with reason, expire; audit on each
- [ ] 5.2 Routes: `POST /leads/{id}/reply-draft`, `GET /reply-drafts`, `POST /reply-drafts/{id}/open|reject|regenerate`; BFF proxies
- [ ] 5.3 Use draft bridge: initiate from lead, prefill compose with `draft_id`, keep compose-draft behaviour intact; origin computed at send
- [ ] 5.4 `voice.expire_drafts` beat task (fact-based: deleted post, ban, any message sent, lead status; no age rule)
- [ ] 5.4a Draft subject = post title truncated to the provider limit; editable in compose
- [ ] 5.5 Web: draft panel on lead detail (text, failed checks, exemplars used, Use draft / Regenerate / Reject); Drafts tab with badge on `/leads`; empty and error states; Vitest

## 6. Automatic preparation

- [ ] 6.1 `reply_draft_policy.evaluate()` pure guard function: match guards vs hard guards, reasons, `not_available` handling; no cap, no age limit; exhaustive unit tests
- [ ] 6.1a Manual path: Draft button on lead detail and lead cards, Save and draft on Browse posts and needs-review items (save/promote first); refuse only ban or missing fact sheet; unmet guards as warnings; no notification
- [ ] 6.2 `voice.prepare_drafts` beat task: enqueue every eligible lead, `jobs` idempotency keyed on lead + identity, generation behind analysis in the inference gate
- [ ] 6.3 `draft_mode` setting on `/settings/voice`, audited; refuses `prepare_and_notify` without a fact sheet
- [ ] 6.4 Integration tests with synthetic data: eligible lead drafted, banned author not drafted, ring suspect not drafted, already-messaged author not drafted, burst of 30 leads yields 30 drafts and no duplicates, manual draft on a low-score lead, nothing is ever sent

## 7. Notifications

- [ ] 7.1 `notifier.py`: `Notifier` protocol, `SlackWebhookNotifier`, allow-list payload builder for `minimal` and `lead`
- [ ] 7.2 Test asserting the payload contains no title, body, username, location or draft text
- [ ] 7.3 `notify.send` on draft ready (one message per draft, no interval), optional quiet hours (off by default), `notify.retry_failed` beat task with capped attempts, `notification_log`, failure isolation; routing test covers the new task names
- [ ] 7.4 Settings UI: configured/not configured, detail level, optional quiet hours, Test button; webhook URL never returned or logged
- [ ] 7.5 Deep link `/leads/<id>?draft=<id>` and `/leads?tab=drafts`

## 8. Measurement, docs, rollout

- [ ] 8.1 Metrics endpoint + `/ops` card: generated, sent unchanged, median edit ratio, reject reasons, expired, reply rate by origin with counts
- [ ] 8.2 CLAUDE.md (tables, tasks, env, notification rule), README, `.env.example` comments
- [ ] 8.3 Deploy; link backfill dry run then live; user curates exemplars and fact sheet
- [ ] 8.4 On-request drafting; then `prepare_and_notify` for one identity with `NOTIFY_DETAIL=minimal`
- [ ] 8.5 After ~30 sent drafts: review metrics; decide on `auto-send-first-messages` and on the LoRA follow-up (≥ 300 confirmed pairs or edit ratio plateau)
