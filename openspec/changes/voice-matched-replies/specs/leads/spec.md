## ADDED Requirements

### Requirement: Contact initiated from a lead is linked to that lead
`POST /conversations/initiate/from-lead/{lead_id}` SHALL record `origin_lead_id` and a snapshot of the post title and resolved body on the conversation it creates, and SHALL leave an existing conversation's origin unchanged when it reuses one. Lead detail SHALL offer a Draft reply action and show the lead's live reply draft.

#### Scenario: New conversation from a lead
- **WHEN** the user initiates contact from lead 42 and no conversation with the author exists
- **THEN** the new conversation has `origin_lead_id=42` and the post snapshot

#### Scenario: Reused conversation
- **WHEN** the user initiates contact from a lead whose author already has a conversation
- **THEN** that conversation is opened and its origin fields are unchanged
