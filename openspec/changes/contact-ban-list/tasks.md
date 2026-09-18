## 1. Schema

- [x] 1.1 Alembic revision: `do_not_contact` + `source`, `status`, `notes`, `cluster_id`, `created_by`, `lifted_at`; lower-case usernames; `lead_posts.status_before_ban`
- [x] 1.2 Model updates

## 2. Ban service and enforcement

- [x] 2.1 `domain/services/ban_list.py`: `is_banned()`, `banned_usernames()` (batched), create, reactivate, lift, bulk, lead status move/restore
- [x] 2.2 Replace the inline queries in `scout_watch.check_author_verdict` and `source_discovery.qualified_account_ids` with the shared predicate
- [x] 2.3 Enforce in both initiation routes, `SendMessageService.validate_send`, the retry endpoint, and `message.send_manual` pre-send
- [x] 2.4 One integration test per outreach path asserting refusal, including case-insensitive match and the queued-then-banned race (synthetic `test_` users only)

## 3. API

- [x] 3.1 `api/routes/ban_list.py` + schemas: list, create, lift, bulk, suggestions, dismiss suggestion; audit on every mutation
- [x] 3.2 Register router; `include_banned` on `GET /leads` and needs-review; batched exclusion
- [x] 3.3 Suggestions query over copy clusters, returning empty when the copy tables are absent
- [x] 3.4 BFF proxies under `apps/web/src/app/api/core/ban-list`

## 4. Web

- [x] 4.1 `BanDialog` (reason presets + notes) and `BannedBanner`
- [x] 4.2 Mount Ban/Lift on conversation header, profile page, lead detail, scout history post, needs-review item, copy-cluster drawer (drawer does not exist yet: handed to post-fingerprint-dedupe 5.5)
- [x] 4.3 Banned view under `/directories` with search, lift, links, empty and error states
- [x] 4.4 Suggestion queue with evidence, ban one, bulk ban with exclusions, dismiss
- [x] 4.5 Compose box handles 409 `counterpart_banned`
- [x] 4.6 Vitest for dialog, banner, view

## 5. Docs

- [x] 5.1 CLAUDE.md: table description, API, safety section
- [x] 5.2 Deploy, smoke: ban and lift a `test_` user end to end
