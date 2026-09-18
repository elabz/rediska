## ADDED Requirements

### Requirement: A user-opened conversation begins with the post it answered, or without the intro
In the dataset export, a conversation whose first message is the user's SHALL begin with the post that message answered as the first `user` turn — a fixed header line naming the location, the title, a blank line and the body, verbatim — when that post is known from the conversation's origin lead snapshot or from a user-confirmed voice exemplar. Unconfirmed or inferred links SHALL NOT be used. When the post is not known, parameter `unlinked_intro` SHALL decide: `drop` (default) SHALL remove the user's opening turn so the sample starts at the counterpart's first message, omitting the conversation if no valid sample remains; `skip` SHALL omit the conversation; `placeholder` SHALL insert the `[conversation initiated]` turn. The audit entry and response SHALL report how many samples used a linked post, had the intro dropped, or were omitted.

#### Scenario: Linked post
- **WHEN** a conversation opened from a lead is exported
- **THEN** its first user turn is the header line followed by the lead's title and body, and the user's intro is the first assistant turn

#### Scenario: Unknown post, default
- **WHEN** a user-opened conversation with no known post and several exchanges is exported with default parameters
- **THEN** the sample starts with the counterpart's first message and the user's intro does not appear

#### Scenario: Intro never answered
- **WHEN** a user-opened conversation with no known post contains only the user's intro
- **THEN** no line is emitted for it

#### Scenario: Reproducing an old dataset
- **WHEN** the export runs with `unlinked_intro=placeholder`
- **THEN** user-opened conversations without a known post begin with `[conversation initiated]` as before
