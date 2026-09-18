## MODIFIED Requirements

### Requirement: Do-not-contact list blocks outreach

The `do_not_contact` table SHALL store provider + username pairs that must never be contacted, each with a source, reason, notes, optional copy-cluster link, and an `active`/`lifted` status; only `active` rows block. Usernames SHALL be compared case-insensitively. Any contact-initiation or send path SHALL check this list through the shared ban predicate and refuse to create a conversation or send a message to a listed username. The profile page SHALL show an account's ban state with its reason and offer Ban and Lift actions.

#### Scenario: Contact attempt against a listed username

- **WHEN** any contact flow targets a username with an active entry on the do-not-contact list
- **THEN** the attempt is blocked and no outgoing message is created

#### Scenario: Lifted entry does not block

- **WHEN** a contact flow targets a username whose only entry is `lifted`
- **THEN** the attempt proceeds normally
