## Why

The do-not-contact list is the system's only outreach blocklist, and it is hollow: the table has zero rows, there is no endpoint or UI to add to it, and the two conversation-initiation routes and `SendMessageService.validate_send` never read it, although the `messaging`, `leads` and `profiles-directories` specs all say they do. Copy detection now produces accounts that should never be approached (scam rings), and the user wants to ban people by hand from a conversation. Both need one working ban list that every outreach path actually honours.

## What Changes

- **The ban list becomes real.** `do_not_contact` gains `source` (`manual`, `copy_ring`, `import`), `status` (`active`, `lifted`), `notes`, `cluster_id`, `created_by`, `lifted_at`. Entries are never deleted; lifting keeps history.
- **Management API and page.** `GET/POST /ban-list`, `POST /ban-list/{id}/lift`, `POST /ban-list/bulk` (ban every author of a copy cluster in one action), with a `/directories` "Banned" view: search by name, reason, source, date, lift, empty and error states.
- **Ban from where the decision happens.** A Ban button (reason required, presets: scam, copy ring, hostile, asked not to be contacted, other) on the conversation header, profile page, lead detail, scout history post, and copy-cluster drawer.
- **Enforcement at every outreach point, fixing the unenforced spec.** Initiate-by-username, initiate-from-lead, and `validate_send` (so an existing conversation is covered too) refuse a banned counterpart with a specific error the UI renders as a banner. The pending-message retry path re-checks. Bans match case-insensitively.
- **Suggestions, never silent bans.** Authors in a `ring_suspect` or `confirmed_ring` cluster (from `post-fingerprint-dedupe`) appear in a suggestion queue with their evidence; one click bans one author or the whole cluster, one click dismisses the suggestion. Nothing is banned without a human action.
- **Consequences of a ban.** An active lead of a banned author moves to `ignored` with reason `banned` (audited, reversible on lift back to its prior status); banned authors are hidden from the default leads list and needs-review queue, skipped by scout analysis (existing behaviour), and never qualify in source discovery (existing behaviour). Incoming messages from a banned account are still synced and shown verbatim, with a banner — nothing is filtered or deleted.

## Non-goals

- No automatic banning, including for confirmed rings of other authors posting later: a new member of a banned cluster becomes a suggestion, not a ban.
- No provider-side block (Reddit block API) and no remote deletion.
- No filtering, hiding or redaction of any stored content or incoming message.
- No ban by pattern, keyword or subreddit.

## Capabilities

### New Capabilities
- `contact-ban-list`: ban entries and lifecycle, management API and page, ban actions across the UI, ring-based suggestions, consequences for leads and queues.

### Modified Capabilities
- `messaging`: sending in an existing conversation and retrying a pending message are refused for banned counterparts (today only initiation is specified, and not enforced).
- `profiles-directories`: the do-not-contact requirement is restated around the extended table and case-insensitive matching.

## Impact

- **DB**: one Alembic revision extending `do_not_contact`; `lead_posts` gains `status_before_ban` (nullable).
- **Core**: new `domain/services/ban_list.py` with the single `is_banned(provider_id, username)` used by `conversation.py` initiation routes, `send_message.py`, `scout_watch.check_author_verdict`, `source_discovery.qualified_account_ids`; new `api/routes/ban_list.py`; leads and needs-review queries exclude banned authors by default.
- **Web**: Ban dialog component, Banned directory view, suggestion queue, banner in conversation and lead detail, BFF proxies.
- **Depends on**: `post-fingerprint-dedupe` only for the suggestion queue and bulk-by-cluster; everything else stands alone and can ship first.
