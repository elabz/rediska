## MODIFIED Requirements

### Requirement: Safety comes from isolation and human control, not censorship

The system SHALL rely on the following controls instead of content filtering: single-researcher access behind authentication; human control of outgoing messages (every outgoing message requires an explicit user action, except first messages sent under the bounded, opt-in, per-identity automatic mode defined in `messaging` and `auto-send`, which is off by default, earned from measured drafting quality, capped, cancellable during a hold window, and self-disabling); the do-not-contact blocklist; the append-only audit log; and local-only data custody. These controls MUST NOT be weakened in exchange for adding content moderation.

#### Scenario: Filtering proposed as a safety measure

- **WHEN** a change proposes adding content filtering as a safety mechanism
- **THEN** the proposal is out of policy; safety changes must strengthen isolation, auditability, or human-in-the-loop controls instead
