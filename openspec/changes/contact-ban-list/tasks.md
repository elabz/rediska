## 1. Schema

- [ ] 1.1 Alembic revision: `do_not_contact` + `source`, `status`, `notes`, `cluster_id`, `created_by`, `lifted_at`; lower-case usernames; `lead_posts.status_before_ban`
- [ ] 1.2 Model updates

## 2. Ban service and enforcement

- [ ] 2.1 `domain/services/ban_list.py`: `is_banned()`, `banned_usernames()` (batched), create, reactivate, lift, bulk, lead status move/restore
- [ ] 2.2 Replace the inline queries in `scout_watch.check_author_verdict` and `source_discovery.qualified_account_ids` with the shared predicate
- [ ] 2.3 Enforce in both initiation routes, `SendMessageService.validate_send`, the retry endpoint, and `message.send_manual` pre-send
- [ ] 2.4 One integration test per outreach path asserting refusal, including case-insensitive match and the queued-then-banned race (synthetic `test_` users only)

## 3. API

- [ ] 3.1 `api/routes/ban_list.py` + schemas: list, create, lift, bulk, suggestions, dismiss suggestion; audit on every mutation
- [ ] 3.2 Register router; `include_banned` on `GET /leads` and needs-review; batched exclusion
- [ ] 3.3 Suggestions query over copy clusters, returning empty when the copy tables are absent
- [ ] 3.4 BFF proxies under `apps/web/src/app/api/core/ban-list`

## 4. Web

- [ ] 4.1 `BanDialog` (reason presets + notes) and `BannedBanner`
- [ ] 4.2 Mount Ban/Lift on conversation header, profile page, lead detail, scout history post, needs-review item, copy-cluster drawer
- [ ] 4.3 Banned view under `/directories` with search, lift, links, empty and error states
- [ ] 4.4 Suggestion queue with evidence, ban one, bulk ban with exclusions, dismiss
- [ ] 4.5 Compose box handles 409 `counterpart_banned`
- [ ] 4.6 Vitest for dialog, banner, view

## 5. Docs

- [ ] 5.1 CLAUDE.md: table description, API, safety section
- [ ] 5.2 Deploy, smoke: ban and lift a `test_` user end to end
