## Context

**What exists.** Identities carry `voice_config_json` (`system_prompt`, `tone`, `style`, `persona_name`), edited on `/settings/personas`. `draft_intro.py` is an unused drafter built on that config (slated for removal). `GET /conversations/export-dataset` already exports whole conversations as ChatML for Unsloth. Inference is `Lumimaid-v0.2-8B` (a Llama-3.1-8B tune, Q5_K_M) on three llama.cpp slots behind LiteLLM, shared with lead analysis through the Redis inference gate. Sending is `POST /conversations/{id}/messages` → `message.send_manual` (`max_retries=0`). The first contact route is `POST /conversations/initiate/from-lead/{lead_id}`; the conversation row keeps no reference to the lead.

**Corpus, measured 2026-09-18 by aggregate queries only (no message content was read):**

| | |
|---|---|
| Conversations opened by the user | 1,052 (2020-09 → today), first message avg 683 chars |
| Got at least one reply | 368 (35%) |
| Reply rate by intro length | < 200 chars 39%, 200–500 38%, 500–1,000 32%, 1,000+ 35% |
| Intro can be paired with a stored lead post by the same author | 140 |
| … or with any stored post by that author in the 14 days before | 192 (18%) |
| Paired **and** replied | 45 |

**Is the post text needed? Yes, it is the most important field.** Three reasons. (1) A human intro is recognisable because it answers something specific in the post; style without a referent produces a generic, template-sounding message, which is what both recipients and Reddit's spam systems react to. (2) Training or prompting on intros without their posts teaches the model that intros contain specifics which appear from nowhere, i.e. to invent them. (3) Retrieval needs the post: the best guide to answering this post is how the user answered a similar one. Unpaired intros are still useful, but only as style samples.

**The existing fine-tuning export, reviewed.** `GET /conversations/export-dataset` (`api/routes/conversation.py`, ~140 lines inline in the route; UI dialog on `/inbox`; BFF proxy; specified in `inbox-conversations`) emits one ChatML conversation per line: outgoing → `assistant`, incoming → `user`. Worth keeping: the message validity filter (not deleted, no `send_error`, visible/unknown), thread-aware ordering, merging of consecutive same-role turns, trailing-user trimming, the `identity_id` / `list_id` / `test_only` filters (conversation lists already work as a hand-curation tool), the audit entry, and the download path through the BFF. Problems: (1) when the user spoke first, it inserts a synthetic `[conversation initiated]` user turn, so for 1,052 of 1,214 conversations the model is trained to produce the intro from a placeholder, which is precisely the behaviour we do not want; (2) `max_tokens` is accepted and never used, so over-length samples are left to the trainer to truncate; (3) one query per conversation and the whole file built in memory behind a `StreamingResponse` that does not stream; (4) no outcome filter, so intros that were ignored weigh the same as ones that worked; (5) no tests, logic untestable inside the route.

**Constraints.** Local inference only (`research-content-policy`). No stored content may go to a third party, which includes Slack. No content filtering. The system is never reachable from the internet, so nothing can call back into it. Coding agents never read inbox content; fixtures are synthetic. The no-autosend rule stays intact in this change.

## Goals / Non-Goals

**Goals:** drafts the user sends with little or no editing; a prompt notification that leaks nothing; a corpus that grows by normal use; numbers that say when the drafter is trustworthy enough to consider automatic sending.

**Non-Goals:** automatic sending, cloud models, inbound Slack, LoRA training now, multi-turn drafting.

## Decisions

**1. Engine A, retrieval-prompted drafting, ships first. Fine-tuning is engine B, optional and later.**

| Approach | Needs | Strength | Weakness |
|---|---|---|---|
| Long system prompt describing the voice | nothing | instant | descriptions of style ("warm, dry humour") barely move an 8B model; output reads like the model, not the user |
| **A. Retrieved post→intro examples + fact sheet** | paired exemplars (works from ~20) | real sentences of the user's steer style far better than adjectives; improves with every sent message; no training loop | bounded by the base model's habits; ~3k-token prompts |
| **B. LoRA fine-tune of the local 8B** | ≥ ~300 paired exemplars for the task; QLoRA fits in ~12 GB VRAM, minutes to train | internalises rhythm, vocabulary, length; short prompts | today only 192 pairs exist; overfits and parrots on small sets; retrain to update; must be re-done per base model |
| Cloud model with a long prompt | — | strongest general writer | out of policy; third parties' posts and private messages leave the LAN; hosted safety layers refuse or sanitise this content |

A and B compose: B can be prompted with retrieved examples too. B is deferred (decision 14).

**2. The unit of the corpus is a triple, and only paired triples teach the task.**
`voice_exemplars(id, identity_id, message_id, post_text, post_title, post_source ENUM(lead, profile_item, snapshot, pasted), lead_id NULL, outcome ENUM(no_reply, replied, engaged), mark ENUM(exemplar, exclude, unreviewed), edit_ratio NULL, created_at)`. Retrieval and dataset export use rows with `mark=exemplar` and non-empty `post_text`. Exemplars without post text are usable only as style samples appended to the prompt ("other messages you wrote"), never as post→intro demonstrations.

**3. Linking the past is assisted, confirmed by the user.**
A backfill proposes, per user-opened conversation, the lead by the same author with the latest post time before the first message, else the latest stored post within 14 days before. Proposals are `unreviewed`. The corpus page shows post and intro side by side with Confirm / Pick another / Paste post text / Not a reply to a post. The backfill runs in-process over IDs and timestamps; it copies text between tables but no agent or log reads it.

**4. Linking the future is automatic.**
`initiate/from-lead` writes `origin_lead_id` and `origin_post_snapshot` (title + resolved body as analysed). The first outgoing message of such a conversation creates an `unreviewed` exemplar with the post attached; if it came from a draft, `edit_ratio` = normalised Levenshtein distance between draft and sent text. Outcome is updated when a reply arrives or the account becomes `engaged`.

**5. Prompt assembly.**
System: the identity's fact sheet ("facts you may state; state nothing else about yourself"), hard rules (no links, no invented shared history, length band = 25th–75th percentile of the user's exemplar lengths, plain text). Then k=4 exemplars as `POST:` / `MY MESSAGE:` pairs, retrieved by post similarity with a bonus for `replied`/`engaged` and a diversity rule (no two exemplars with cosine > 0.9 to each other), then up to 3 unpaired style samples, then the new post and the analysis facts worth using (shared interests from the preferences dimension). Temperature 0.8, two candidates generated, the verifier picks. The full prompt and the exemplar IDs are stored on the draft for audit and for the evaluation page.

**6. Verification before a draft is shown as sendable.**
Deterministic: length band; no URL, no username other than the recipient, no markdown artefacts or assistant phrases ("As an AI", "I hope this message finds you"); cosine < 0.90 against every intro sent in the last 90 days (repetition is what gets accounts flagged); not a near-copy of a retrieved exemplar (Jaccard < 0.5). LLM verifier (same local model, separate call, JSON out): lists every claim about the sender and marks each as supported by the fact sheet or not; names the specific post detail the draft responds to. Any unsupported claim or no specific → the draft is `needs_edit`, shown with the failed checks.

**7. Trust is measured from normal use.**
(a) **Edit ratio** of sent drafts (normalised Levenshtein between draft and sent text) — free and continuous. (b) **Share sent unchanged**, and **reject reasons**. (c) **Reply rate by origin** (`manual`, `draft_edited`, `draft_as_is`) with counts, because small samples lie. Shown per identity and engine on `/ops`. A blind "which one is yours" test is deferred with the fine-tune, where it is needed to compare engines.

**8. A reply draft is a server-side record with a lifecycle, separate from compose drafts.**
`reply_drafts(id, lead_id, identity_id, status, body, subject, engine, model, prompt, exemplar_ids_json, checks_json, guards_json, trigger ENUM(on_request, prepared), created_at, notified_at, opened_at, resolved_at, message_id NULL, reject_reason NULL, superseded_by NULL)`. Statuses: `generating → ready | needs_edit → notified → opened → sent | rejected | expired`. One live draft per (lead, identity); regenerating supersedes. `message-drafts` (browser localStorage, keyed by conversation) stays what it is: the scratchpad of the compose box. The bridge is one step: **Use draft** initiates the conversation from the lead (existing route), puts the draft body into the compose box with `draft_id` attached, and marks the draft `opened`. Sending is the ordinary explicit send; the send path stamps `messages.draft_id` and `origin` (`draft_as_is` when the text is unchanged, `draft_edited` otherwise) and resolves the draft to `sent`. *Alternative:* a Send button on the draft itself — rejected for now: one send path keeps ban checks, at-most-once semantics and the 7-row compose habits in one place.

**9. Drafts expire on facts, not on age.**
`voice.expire_drafts` marks a live draft `expired` when the post is deleted/removed, the author becomes banned, any message has been sent to the author, or the lead leaves `new`/`saved`. There is no age limit (user decision): an old post by someone never messaged is still worth a draft. Expired drafts are kept as evidence and drop out of the Drafts tab.

**10. One guard function, two callers, no quotas.**
`reply_draft_policy.evaluate(lead, identity) → (eligible, reasons[])`, pure and exhaustively unit-tested. *Match guards:* recommendation `suitable`, priority `high`, all gates passed, compatibility ≥ `DRAFT_MIN_COMPATIBILITY` (0.75), no disagreeing human evaluation, status `new`/`saved`, not in a ring-suspect cluster, location without `contact_rule`. *Hard guards:* author not banned, no message ever sent to the author (no existing conversation with an outgoing message), account alive, post visible, identity has a fact sheet. Automatic preparation requires all of them. The manual Draft button requires only "not banned" and "fact sheet present"; every other failed guard is returned as a warning shown on the draft, because the user asking for a draft *is* the judgement the match guards stand in for. There is no daily cap and no post-age limit (user decision: drafting is internal and costs only local GPU time). Pacing comes from the inference gate: `voice.generate_draft` runs on the `agent` queue behind lead analysis, so a burst of eligible leads becomes a queue, not an outage. `voice.prepare_drafts` (beat, 5 min) only enqueues; `jobs` idempotency keyed on (lead, identity) prevents duplicates.

**10a. Draft on demand, from wherever the lead was found.**
`POST /leads/{id}/reply-draft` backs a Draft button on lead detail and lead cards. On Browse posts and needs-review items the button is "Save and draft": it saves/promotes to a lead through the existing routes, then requests the draft, so there is still exactly one way a lead comes into being. Manual drafts do not notify (the user is looking at the screen); they appear in place with a progress state.

**11. Notifications: content-free, immediate, outbound-only, behind an interface.**
`Notifier` protocol with `SlackWebhookNotifier` as the first implementation (an incoming-webhook POST; no Slack app, no bot token, no scopes). The payload is assembled from an allow-list of fields, never from free text: `minimal` → "A reply draft is waiting" + `BASE_URL/leads/<id>?draft=<id>`; `lead` → adds lead id, priority, compatibility, draft status. No title, body, draft text, username, subreddit or listing URL at any level; a unit test asserts the serialised payload contains no value from those columns. One message per prepared draft, sent as soon as the draft reaches `ready`/`needs_edit` (user decision: no batching interval). Slack's webhook limit (about one message per second) is far above what the inference gate can produce. Optional quiet hours, off by default, hold notifications and release them together when the window ends. Each attempt is recorded in `notification_log`; a failure is retried by `notify.retry_failed` (beat, 5 min, capped attempts) and never affects drafting. The link only resolves on the LAN/VPN, so Slack learns that something is waiting and nothing about what. *Alternatives:* self-hosted ntfy or Gotify behind the same interface later; Slack interactive buttons — impossible without exposing an endpoint to the internet; email — same content rule, more setup.

**11a. The subject is the post's title.**
For providers whose first message carries a subject (Reddit PMs), the draft's subject is the title of the post being answered, truncated to the provider's limit (user decision). It is never generated. The subject is sent to the provider as part of the message; it never appears in a notification.

**12. The webhook URL is a secret.**
`SLACK_WEBHOOK_URL` comes from the environment (and must be added to the compose environment blocks, or it silently does nothing). It is never returned by an API or written to the audit log; the settings page shows only whether it is configured and offers a Test button that sends "Rediska test notification".

**13. Reuse the dataset export; do not build a second exporter.**
The five problems listed in Context are fixed by their own changes: `dataset-export-service-tests` (extraction + characterisation tests, lands first), `dataset-export-intro-context` (placeholder), `dataset-export-token-limit`, `dataset-export-streaming`, `dataset-export-outcome-filter`. This change contributes two things. It supplies the confirmed post links (`origin_post_snapshot`, confirmed exemplars) that the intro-context change reads. And it adds `mode=intros` to the same endpoint and dialog: one sample per confirmed paired exemplar — system (fact sheet), user (post), assistant (intro) — with `min_outcome`, `identity_id`, `list_id`, held-out exclusion, using the shared `conversation_outcome()` function so exemplar outcomes and export outcomes never disagree.

**14. LoRA fine-tuning: later, deliberately.**
Not now, for four reasons. (a) *Data:* 192 pairs, 45 with a reply; a task LoRA on an 8B model wants a few hundred clean pairs, and below that it memorises and parrots. (b) *No baseline:* without edit-ratio numbers from the retrieval drafter there is nothing to show a fine-tune is better, and the retrieval drafter may be good enough. (c) *The bottleneck is pairing, not training:* the work that makes a future fine-tune possible — post linkage, corpus marking, outcome tracking, the corrected export — is all in this change and is needed by the retrieval drafter anyway. (d) *Cost of waiting is nil:* training an 8B QLoRA takes minutes once the data exists, and the base model may change before then. What is done now so that "later" is cheap: the `intros` export, held-out flagging, `engine`/`model` recorded on every draft so engines can be compared, and `VOICE_MODEL` as a setting. Revisit when there are ≥ 300 confirmed pairs, or when the median edit ratio plateaus above ~0.25 despite a growing corpus. The training recipe and the blind test page move to that follow-up.

## Risks / Trade-offs

- [Notification leaks sensitive context to Slack] → allow-listed fields only, test asserting no content columns appear, `minimal` as default, link resolvable only on the LAN/VPN.
- [Notification noise] → only leads passing every guard notify; manual drafts do not; optional quiet hours. Volume is bounded in practice by how many high-match leads exist (about 1–2 a day today, about 15 if every post is read).
- [The model invents facts about the user] → fact sheet plus claim-level verifier; failing drafts are `needs_edit`, shown with the reasons.
- [The draft sounds like the model, not the user] → retrieved real sentences; edit ratio is the honest measure, visible on `/ops`.
- [Drafts pile up unread] → fact-based expiry, Drafts badge; rejected/expired drafts still count as evidence.
- [Two "draft" concepts confuse] → naming: *reply draft* (server, generated) vs *compose draft* (browser, typed); one bridge action.
- [GPU contention with analysis] → drafts queue behind analysis at the inference gate; two candidates + one verifier ≈ 3 calls per draft, always behind analysis in the gate.
- [Export change breaks an existing training workflow] → default mode and placeholder behaviour for unlinked conversations are unchanged.

## Migration Plan

1. Revision; origin linkage on initiate; export refactor (behaviour-preserving) with tests.
2. Corpus page, fact sheet, link backfill (dry run first). User curates.
3. On-request drafting on lead detail. Edit ratios start accumulating.
4. `prepare_and_notify` for one identity, `NOTIFY_DETAIL=minimal`.
5. Review metrics after ~30 sent drafts; decide on `auto-send-first-messages` and on the LoRA follow-up.
Rollback: set `draft_mode=on_request`, unset `SLACK_WEBHOOK_URL`; tables are additive.

## Open Questions

- Should `needs_edit` drafts notify? Proposed: yes, labelled, because a draft needing a small fix still saves most of the time.
