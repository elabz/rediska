# research-content-policy Specification

## Purpose
Rediska is a social-studies research instrument. The research examines human sexuality and online relationship-seeking behavior, so the material the system ingests from provider platforms (personals-style posts, profile content, private conversations) is inherently sensitive and adult in nature. This spec records the project's standing policy: that material is in scope for the research and must be handled verbatim, and the system's safety posture comes from strict local isolation and human-in-the-loop controls — not from content filtering.

## Requirements

### Requirement: Sensitive content is in scope and stored verbatim

The system SHALL store, index, display, and analyze ingested content exactly as retrieved from the provider, including adult and sexuality-related material. No layer of the system (ingest, storage, search, LLM analysis, UI) may censor, redact, moderate, paraphrase-for-safety, or refuse to process content on the basis of its adult or sensitive nature.

#### Scenario: Adult post is ingested

- **WHEN** browse, scout watch, or profile fetch retrieves a post or comment containing explicit adult content
- **THEN** the content is persisted, indexed, and embedded verbatim
- **AND** it is rendered unaltered in the UI
- **AND** no filtering, masking, or warning-gating is applied

#### Scenario: LLM analysis of sensitive dimensions

- **WHEN** the multi-agent analysis runs (including the Sexual Preferences dimension)
- **THEN** agents analyze the full unfiltered content
- **AND** results are stored and displayed without redaction

### Requirement: The system is never accessible from the public internet

The system SHALL be reachable only from the operator's LAN or private VPN (Tailscale). No deployment, configuration change, or feature may expose any part of the stack — UI, APIs, databases, search, or LLM endpoints — to the public internet, and no ingested content may be sent to third-party cloud services.

#### Scenario: Deployment review

- **WHEN** any deployment or infrastructure change is made
- **THEN** no compose service publishes ports beyond the local reverse proxy's LAN/VPN-scoped listener
- **AND** LLM inference and embeddings continue to run on locally-hosted endpoints (llama.cpp), not hosted APIs

#### Scenario: Proposed feature requiring an external service

- **WHEN** a proposed change would transmit stored content to an external/cloud service
- **THEN** the change is rejected or redesigned to keep content local

### Requirement: Safety comes from isolation and human control, not censorship

The system SHALL rely on the following controls instead of content filtering: single-researcher access behind authentication; no autosend (every outgoing message requires an explicit user action); the do-not-contact blocklist; the append-only audit log; and local-only data custody. These controls MUST NOT be weakened in exchange for adding content moderation.

#### Scenario: Filtering proposed as a safety measure

- **WHEN** a change proposes adding content filtering as a safety mechanism
- **THEN** the proposal is out of policy; safety changes must strengthen isolation, auditability, or human-in-the-loop controls instead

### Requirement: AI agents must not read Inbox content

AI coding agents and automation working on this project SHALL NOT read the content of the Inbox or of individual messages/conversations (e.g. pages matching `https://rediska.local/inbox/[0-9]+`), through any channel — browser, API, database queries, or logs. Working on inbox-related code is permitted; inspecting inbox data is not.

#### Scenario: Agent debugging an inbox feature

- **WHEN** an AI agent needs to verify inbox-related code changes
- **THEN** it works from code, tests, and synthetic data only
- **AND** it does not open live conversation pages or query live message rows
