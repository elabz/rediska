## Why

Writing a first message to each high-match lead by hand is the slowest step left in the workflow, and the best leads go stale while they wait. The user wants replies written in their own voice and, eventually, sent automatically. The safe road there is to make the system prepare a draft, tell the user it is waiting, and let them send it: every draft the user sends unchanged is evidence the drafter can be trusted, and every edit is training data. The raw material exists (1,052 conversations opened by the user, 35% of which got a reply) but is not usable yet: conversations carry no link to the post they answered, only 192 intros (18%) can be paired with stored post text, and the existing fine-tuning export fills that gap with a `[conversation initiated]` placeholder, which teaches a model to write intros from nothing.

## What Changes

- **Reply drafts become a first-class, server-side object.** A `reply_draft` belongs to a lead and an identity, holds the generated text, the evidence behind it (exemplars used, checks passed or failed, model), and a lifecycle: `generating → ready | needs_edit → notified → opened → sent | rejected | expired`. It is distinct from the browser-side compose drafts of `message-drafts`: opening a reply draft loads its text into the normal compose box, and from there the normal send rules apply. Nothing in this change sends a message.
- **Drafts are prepared automatically for high-match leads.** Per identity, draft preparation is `on_request` (default) or `prepare_and_notify`. In the second mode, a lead that is `suitable`, high priority, all gates passed, at or above compatibility 0.75, not banned, never messaged before, not a ring suspect, and from a location without a contact restriction gets a draft without being asked. Drafting is an internal function, so there is no daily cap and no post-age limit; the inference gate paces the work behind lead analysis.
- **A Draft button for any lead.** Leads found another way (saved from Browse, added by hand, promoted from needs-review, or simply below the automatic thresholds) get a draft on demand from lead detail and lead cards; Browse posts and needs-review items offer Save and draft. The manual path skips the match guards and shows them as warnings; it refuses only a banned author or an identity without a fact sheet.
- **Slack tells the user a draft is waiting — and nothing else.** A notification says a draft is ready and links to it on `rediska.local`, reachable only from the LAN/VPN. By policy it carries no post text, no draft text and no usernames; the default message is a count and a link, and an optional detail level adds the lead id, priority and compatibility. One notification is sent as soon as each prepared draft is ready; optional quiet hours (off by default) hold them until morning; a failed delivery is retried and never blocks or fails anything. Approving or sending from Slack is not possible by design, because that would require the system to accept traffic from the internet.
- **Every intro is tied to the post it answers, from now on.** Initiating from a lead records `origin_lead_id` and a snapshot of the post on the conversation. Past intros get proposed links the user confirms, corrects or clears.
- **A voice corpus the user curates.** The user marks their own intros as `exemplar` or `exclude` (individually, or in bulk from an existing conversation list). An exemplar is a triple: post text, intro text, outcome. Sent drafts join the corpus automatically with the edit distance between draft and sent text. A fact sheet per identity bounds what a draft may claim about the sender.
- **Drafting by retrieved examples, on the local model.** The system retrieves the user's exemplars whose posts are most similar to this one (via `semantic-similarity-search`), prefers ones that got replies, and prompts the local model with the fact sheet, those post→intro pairs and the new post. Verification rejects drafts that state facts absent from the fact sheet, respond to nothing specific, contain links, or nearly repeat an intro already sent.
- **The existing fine-tuning export is reused, not duplicated.** Its defects are fixed by five separate changes (`dataset-export-service-tests`, `-intro-context`, `-token-limit`, `-streaming`, `-outcome-filter`). This change only adds an `intros` mode that emits post→intro pairs from confirmed exemplars, and supplies the post links that `dataset-export-intro-context` consumes. LoRA training itself is deferred: the corpus is too small today and there is no baseline to beat yet (see design).
- **Trust is measured.** Edit ratio of sent drafts, share sent unchanged, reject reasons, and reply rate by message origin are reported per identity. These numbers are the entry criteria for `auto-send-first-messages`, a separate, later change.

## Non-goals

- **No automatic sending.** The no-autosend rule is untouched; every message still needs an explicit send. Automatic sending is proposed separately in `auto-send-first-messages` and depends on the evidence this change collects.
- No cloud LLM (Gemini or other): `research-content-policy` forbids sending stored content to third parties, and these prompts would carry other people's posts and the user's private messages.
- No content in notifications, and no inbound Slack integration (buttons, slash commands, bots).
- No LoRA training procedure or training inside the app now; only the dataset export is kept ready.
- No drafting of replies beyond the first message.
- No content filtering of drafts or posts.

## Capabilities

### New Capabilities
- `voice-replies`: reply drafts and their lifecycle, automatic preparation with guards, voice corpus and fact sheet, post–intro linkage for past intros, retrieval-prompted generation, verification, metrics.
- `notifications`: outbound, content-free notifications (Slack webhook first), immediate delivery, optional quiet hours, retry, failure isolation.

### Modified Capabilities
- `messaging`: outgoing messages record their origin (manual, draft edited, draft as-is) and the draft they came from.
- `leads`: initiating contact from a lead links the conversation to the lead and post snapshot; lead detail shows the reply draft.
- `inbox-conversations`: the fine-tuning dataset export gains an `intros` mode.
- `research-content-policy`: a new requirement that outbound notifications carry no stored content.

## Impact

- **DB** (one revision): `conversations.origin_lead_id`, `origin_post_snapshot`; `messages.origin`, `messages.draft_id`; `reply_drafts`; `voice_exemplars`; `voice_fact_sheets`; `identities.draft_mode` + thresholds; `notification_log`.
- **Core**: `domain/services/voice_reply.py`, `voice_corpus.py`, `reply_draft_policy.py` (guards as one pure function, reused later by auto-send), `notifier.py`, an `intros` mode in `dataset_export.py` (the service created by `dataset-export-service-tests`); routes `/reply-drafts/*`, `/voice/*`; replaces the unused `draft_intro.py` (coordinate with `remove-dead-weight`).
- **Worker**: `voice.generate_draft` (queue `agent`, inference gate, `jobs` idempotency), `voice.prepare_drafts` (beat, 5 min), `notify.send` (immediate, per draft) with `notify.retry_failed` (beat), `voice.backfill_links`, `voice.expire_drafts`.
- **Web**: Drafts tab on `/leads` with a badge count; draft panel on lead detail; corpus marking in the conversation view; `/settings/voice` (fact sheet, exemplars, draft mode, notification settings with a Test button); metrics card on `/ops`; export dialog gains the mode switch.
- **Settings**: `SLACK_WEBHOOK_URL` (secret), `NOTIFY_DETAIL` (`minimal`|`lead`), `DRAFT_MIN_COMPATIBILITY` (0.75) — in `.env.example` and the compose environment blocks.
- **Network**: the worker makes one kind of outbound HTTPS call to `hooks.slack.com`. No port is opened and nothing becomes reachable from outside.
- **Depends on**: `semantic-similarity-search` (exemplar retrieval, repetition check); `dataset-export-service-tests` for the `intros` mode only. `contact-ban-list` and `post-fingerprint-dedupe` strengthen the guards; when absent, their guards are skipped and the draft is labelled accordingly.
- **Privacy**: prompts contain the user's own messages; this is an in-system function on the local model. AI coding agents still must not read inbox content — tests and fixtures use synthetic `test_` conversations.
