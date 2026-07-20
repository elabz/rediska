# identity-management Specification

## Purpose
An identity is a persona the user acts through on a provider (e.g. a Reddit account), including an optional LLM "voice" configuration. The system supports multiple identities per provider, exactly one default per provider, identity-bound conversations and outgoing messages, and OAuth-based identity creation with encrypted credential storage.

## Requirements

### Requirement: Identities are managed through CRUD endpoints

The core API SHALL expose `GET /identities` (flat or grouped by provider), `POST /identities`, `GET /identities/{id}`, `PATCH /identities/{id}`, `DELETE /identities/{id}`, and `POST /identities/{id}/set-default`.

#### Scenario: Listing grouped by provider

- **WHEN** a client calls `GET /identities` with grouping requested
- **THEN** identities are returned grouped under their provider with display name, active flag, and default flag

#### Scenario: Updating an identity

- **WHEN** the user PATCHes an identity with a new `display_name` or `voice_config_json`
- **THEN** the changes persist and are reflected in subsequent reads

### Requirement: Exactly one default identity per provider

Each provider SHALL have at most one default identity. Setting a new default SHALL clear the previous default for that provider. The first identity created for a provider SHALL become its default automatically.

#### Scenario: Set-default is exclusive

- **WHEN** the user calls `POST /identities/{id}/set-default` for provider P
- **THEN** that identity's `is_default` becomes true
- **AND** every other identity of provider P has `is_default` false

#### Scenario: First identity defaults automatically

- **WHEN** the first identity for a provider is created
- **THEN** it is marked as that provider's default without further user action

### Requirement: Voice/persona configuration per identity

Each identity SHALL support a `voice_config_json` (system prompt, tone, style, persona name) used when the LLM generates content on behalf of that identity. The web app SHALL expose this via the Personas settings page (`/settings/personas`).

#### Scenario: Persona editing

- **WHEN** the user edits a persona's tone, style, or system prompt in `/settings/personas`
- **THEN** the identity's `voice_config_json` is updated via `PATCH /identities/{id}`
- **AND** subsequent LLM draft generation for that identity uses the updated voice configuration

### Requirement: Conversations and outgoing messages are identity-bound

Every conversation SHALL be associated with exactly one identity at creation, and the identity SHALL NOT change mid-conversation. Outgoing messages SHALL record the identity that sent them; incoming messages carry no identity.

#### Scenario: New conversation uses selected or default identity

- **WHEN** a conversation is initiated with an explicit `identity_id`
- **THEN** the conversation is bound to that identity
- **AND** when no `identity_id` is supplied, the provider's default identity is used

#### Scenario: Outgoing message records its identity

- **WHEN** a message is sent in a conversation
- **THEN** the stored message row references the conversation's identity

### Requirement: Deactivation preserves history

Deleting an identity SHALL be a soft deactivation: existing conversations bound to it remain readable, but the identity is no longer offered for new conversations.

#### Scenario: Deactivated identity's conversations stay readable

- **WHEN** the user deletes an identity that owns existing conversations
- **THEN** those conversations and their messages remain visible in the inbox
- **AND** the identity is excluded from identity selectors for new outgoing activity

### Requirement: OAuth flow creates identities with encrypted credentials

`GET /providers/reddit/oauth/start` SHALL return an authorization URL with a state token; `GET /providers/reddit/oauth/callback` SHALL validate state, exchange the code for tokens, fetch the provider user identity, and create or reuse the matching identity. OAuth tokens SHALL be stored encrypted (Fernet, `ENCRYPTION_KEY`) in `provider_credentials`, never in plaintext.

#### Scenario: Completing OAuth creates or reuses an identity

- **WHEN** the OAuth callback completes for a Reddit account
- **THEN** an identity is created for that `external_username` if none exists, or the existing one is reused
- **AND** refresh/access tokens are stored encrypted in `provider_credentials` linked to the identity
- **AND** the action is written to the audit log

#### Scenario: Onboarding via OAuth popup

- **WHEN** the user starts the connection flow from `/setup/identity` or `/settings/connection`
- **THEN** OAuth runs in a popup that posts `oauth_complete` back to the opener on success
- **AND** the opener refreshes state (onboarding proceeds to the inbox once an identity exists)
