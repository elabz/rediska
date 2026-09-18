## Context

`DoNotContact(provider_id, external_username, reason, created_at)` exists since migration 001. Readers today: `scout_watch.check_author_verdict` (skip analysis) and `source_discovery.qualified_account_ids` (never qualifies). Writers: none. `api/routes/conversation.py` `initiate_conversation_from_lead` and `initiate/by-username` do not query it; `SendMessageService.validate_send` blocks only `remote_status in {deleted, suspended}`. The specs claim otherwise, so this change is partly a defect fix.

## Goals / Non-Goals

**Goals:** one ban predicate used everywhere; manual ban in two clicks from any surface; ring suggestions with evidence; full audit and reversibility.

**Non-Goals:** automatic bans, provider-side blocks, content filtering.

## Decisions

**1. Extend `do_not_contact`, do not add a second table.**
Existing readers keep working, the specs already name it, and "banned" and "do not contact" are the same promise. *Alternative:* a new `banned_accounts` table keyed by `account_id` — rejected: bans must work for usernames we have never stored (ring members seen only in a fingerprint), and a second list invites the same drift that made this one hollow.

**2. Username is the key; match on `LOWER(external_username)`.**
Reddit usernames are case-insensitive. The migration lower-cases existing rows (none today) and the unique constraint moves to the lowered value. `account_id` is resolved at read time, not stored, so bans survive account-row merges.

**3. Status instead of delete.**
`lifted` rows stay for history; re-banning a lifted username reactivates the same row and appends to `notes`. The unique key stays `(provider_id, username)`.

**4. Enforcement in `validate_send`, not only at initiation.**
A ban most often happens mid-conversation. `validate_send` raises `CounterpartBannedError`; the route maps it to 409 with code `counterpart_banned`; the compose box shows a banner with a Lift link instead of failing silently. The worker task `message.send_manual` re-checks immediately before the provider call, because a message can be queued before the ban lands.

**5. Lead consequence is a status move, remembered.**
Active leads (`new`, `saved`, `contact_queued`) of a banned author go to `ignored`, with the prior status in `status_before_ban`; lifting restores it. `contacted` leads are left alone — history is not rewritten. Analysis rows are never touched (analysis retention rule).

**6. Suggestions are a query, not a table.**
Suggestion = author in a cluster whose effective kind is `ring_suspect`/`confirmed_ring`, not banned, not dismissed. Dismissal is stored on `copy_cluster_members.ban_suggestion_dismissed_at`. When `post-fingerprint-dedupe` is absent the endpoint returns an empty list.

**7. Bulk ban is one audited batch.**
`POST /ban-list/bulk {cluster_id, reason, exclude_usernames[]}` writes one row per author and a single `ban.bulk_create` audit entry listing them.

## Risks / Trade-offs

- [Banning an innocent author whose ad was copied by a ring] → bulk dialog lists every author with first-post time and marks the earliest poster; per-author exclude; lift restores lead status.
- [Hiding banned authors' leads makes mistakes invisible] → Banned directory view links each entry's leads; leads list has `include_banned=true`.
- [Race between ban and queued send] → worker-side re-check.
- [Spec drift happens again] → one integration test per outreach path asserts refusal for a banned username.

## Migration Plan

Additive revision; deploy; no backfill needed (table is empty). Rollback: downgrade drops the new columns; enforcement code tolerates their absence only before upgrade, so roll back code and schema together.

## Open Questions

- Should a ban also archive the conversation? Proposed: no, the user can archive; the banner is enough.
