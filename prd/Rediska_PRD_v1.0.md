# Rediska – Product Requirements Document v1.0

**Date:** 2026-07-19
**Status:** Consolidated baseline — supersedes Spec Pack v0.3–v0.5, Sprint Plan v0.2, Task Breakdown v0.2, and Implementation Plan v0.5 as the single product-level document. Behavioral requirements now live in the OpenSpec capability specs (`openspec/specs/`); this PRD is the product-level view that ties them together.

---

## 1. Background & Research Context

Rediska is a **social-studies research instrument** built and operated by a single researcher. The research examines human sexuality and online relationship-seeking behavior on social platforms (initially Reddit personals-style communities). The system discovers relevant public posts, analyzes their authors with locally-hosted LLMs, and supports manual, human-initiated outreach and conversation management — while preserving every piece of collected data locally.

### 1.1 Content policy (no censorship)

The themes this system deals with are of a sensitive, adult nature and are **explicitly within the scope of the research**. Consequently:

- The system stores, indexes, displays, and analyzes ingested content **verbatim**. There are **no censorship requirements of any kind**: no content filtering, moderation, redaction, or refusal layers may be added to ingest, storage, search, LLM analysis, or the UI.
- The counterbalancing safety posture is **isolation and human control**, not filtering: the system is **not accessible online and must never be made accessible online** (LAN/private VPN only), all content stays on local infrastructure (including LLM inference via llama.cpp — no cloud AI APIs), every outgoing message requires an explicit human action, and all mutations are audited.
- See `openspec/specs/research-content-policy/spec.md` for the normative version of this policy, including the prohibition on AI coding agents reading live Inbox content.

## 2. Product Overview

A local-first, single-user web application ("conversation management and lead discovery") that:

1. **Connects** the researcher's provider accounts (Reddit OAuth) as one or more *identities*, each with an optional LLM "voice" persona.
2. **Discovers** candidate posts ("leads") by manual browsing of provider locations (subreddits) or by automated saved searches ("Scout Watches") that run on a schedule.
3. **Analyzes** lead authors with a 6-agent LLM pipeline (Demographics, Preferences, Relationship Goals, Risk Flags, Sexual Preferences, Meta-Analysis) producing a recommendation (suitable / not_recommended / needs_review) with confidence, backed by versioned, editable agent prompts.
4. **Manages outreach** through an inbox: conversation sync, manual message sending (no autosend), drafts, search, labels/lists, attachments, and per-counterpart profile panels.
5. **Tracks the contact lifecycle** through directories: analyzed → contacted → engaged, plus starring and a do-not-contact blocklist.
6. **Preserves data**: provider deletions never remove local records or files; backups and restore tests run on a schedule; conversations can be exported (HTML, and ChatML JSONL fine-tuning datasets).

### 2.1 Core principles (locked)

| Principle | Meaning |
|---|---|
| Local storage only | DB/search/queue in Docker volumes; attachments/backups on the local filesystem. Nothing leaves the host. |
| Never online | Reachable only via LAN/private VPN (Tailscale). No public exposure, ever. |
| No censorship | Content handled verbatim (see §1.1). |
| Provider-agnostic core | "reddit" appears only in the provider module and provider-scoped endpoints. |
| No remote deletes | Provider-side deletions only mark `remote_status`/`remote_visibility` locally. |
| No autosend | Every send requires an explicit user click. |
| Single user | One local admin account; cookie sessions. |
| Auditability | Every mutating endpoint writes the append-only `audit_log`; every Celery task uses the `jobs` idempotency ledger. |

## 3. Users

One user: the researcher/operator (admin). There are no other roles, no multi-tenancy, and no anonymous access.

## 4. Functional Areas

Each area below is specified normatively in `openspec/specs/<capability>/spec.md`.

| Area | Capability spec(s) | Summary |
|---|---|---|
| Auth & onboarding | `auth-session` | Bootstrap first admin, cookie-session login, onboarding gate until an identity exists. |
| Identities & personas | `identity-management` | Multiple identities per provider, one default, voice/persona config, Reddit OAuth with encrypted tokens. |
| Provider integration | `provider-reddit` | ProviderAdapter abstraction; Reddit adapter (conversations, messages, browse, profiles, send, remote delete); Redis rate limiting. |
| Sync & ingest | `conversation-sync` | Backfill + delta sync (120s) + fast inbox sync (60s); idempotent jobs; no remote deletes. |
| Inbox | `inbox-conversations`, `conversation-search`, `inbox-search`, `message-drafts` | Conversation list/detail, lists (labels), threading, star, search with jump-to-match, autosaved drafts, exports. |
| Messaging | `messaging` | Manual send only, retry/pending/failed handling, initiate by username or from lead, do-not-contact enforcement, remote-delete (single/batch). |
| Attachments | `attachments` | Local-FS storage with hashes; upload/download; re-download of missing images. |
| Discovery | `browse-discovery` | Browse subreddit feeds with sort/time/query presets; save leads; auto-accumulate posts of known authors as profile items. |
| Leads | `leads` | Lead lifecycle (new/saved/ignored/contact_queued/contacted); saving a lead also persists the post as a profile item; auto-analyze on save. |
| LLM analysis | `lead-analysis` | 6-agent multi-dimensional analysis; analysis resilience (works from as little as one post); versioned agent prompts with rollback; interests/character summaries. |
| Scout Watches | `scout-watch` | Scheduled saved searches; per-post pipeline (fetch profile → summarize → analyze); auto-promote to leads above a confidence threshold; run history + retention cleanup. |
| Profiles & directories | `profiles-directories` | External account states (analyzed/contacted/engaged/starred), profile snapshots + items, duplicate detection, do-not-contact. |
| Search | `search-indexing` | Hybrid (BM25 + kNN) / text / vector search over messages, leads, profiles, conversations; llama.cpp embeddings. |
| Ops & jobs | `ops-jobs` | Job ledger + retry, backfills, consistency checks, sync status, metrics endpoints, audit log viewer. |
| Backups | `backup-restore` | Daily DB dump + attachment snapshots, weekly restore test, checksums, local-only targets. |
| Platform & deploy | `deployment-platform` | Compose stack with no published host ports behind an external dev-proxy (TLS); GHCR images; CD via GitHub Actions + Tailscale SSH; Alembic migrations. |
| Research policy | `research-content-policy` | §1.1 above, normatively. |

## 5. Architecture (as built)

```
Browser (LAN/VPN) → dev-proxy (external repo, TLS, rediska.local vhost)
                       → rediska-web  (Next.js 14 App Router, BFF proxy routes)
                          → rediska-core (FastAPI)  → MySQL 8.4 / Elasticsearch 8.14 / Redis 7
                                                    → enqueues Celery jobs
                       rediska-worker / rediska-beat (Celery) → Reddit API, llama.cpp (inference + embeddings)
```

- **BFF pattern**: the UI only calls same-origin `/api/core/*` Next.js routes, which forward the session cookie to FastAPI. The UI never calls the Python backend directly.
- **The former in-repo `rediska-nginx` service is retired**; TLS and the `rediska.local` vhost live in the shared external `dev-proxy` stack, which attaches to the `rediska-net` Docker network. No compose service publishes host ports.
- **LLM runtime** is external llama.cpp endpoints configured via `INFERENCE_*` / `EMBEDDINGS_*` env, with a configurable chat template (llama3, qwen_thinking, mistral, chatml).
- ~24 MySQL tables (head migration: `017_add_conversation_lists`), including scout watch tables, multi-agent analysis tables, conversation lists, and message threading columns.

## 6. Non-Functional Requirements

- **Privacy/custody**: all data local; OAuth tokens Fernet-encrypted at rest; passwords Argon2; sessions httpOnly+Secure; only the reverse proxy is LAN-exposed.
- **Durability**: no remote deletes; append-only audit log; scheduled backups with checksums and restore verification.
- **Reliability**: Celery tasks idempotent via the `jobs` ledger with dedupe keys and bounded retries; `message.send_manual` is at-most-once (max_retries=0).
- **Rate limiting**: per-provider QPM/concurrency/burst limits enforced via Redis.
- **UX baseline**: every page has empty and error states; lint and tests must pass before merge.

## 7. Out of Scope (v1)

- Additional providers beyond Reddit (the adapter interface exists; nothing else is implemented).
- Autosend / automated outreach of any kind.
- Cloud storage, cloud LLM APIs, NAS backup targets (backup targets kept pluggable).
- Multi-user access, roles, or public exposure.

## 8. Document Map

| Document | Role |
|---|---|
| `openspec/specs/*/spec.md` | Normative capability requirements (source of truth). |
| `openspec/changes/` | In-flight and archived change proposals (OpenSpec workflow). |
| This PRD | Product-level consolidation and rationale. |
| `CLAUDE.md` | Developer/AI-assistant guide to the codebase. |
| `docs/deploy.md` | Operator deploy/migration/troubleshooting guide. |
| `prd/Rediska_Spec_Pack_v0.5.md` and older | Historical; superseded by this PRD + OpenSpec. |
| `tasks/` | Historical task files and design docs (Scout Watch, multi-agent analysis). |
