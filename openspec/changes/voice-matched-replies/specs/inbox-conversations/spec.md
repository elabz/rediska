## ADDED Requirements

### Requirement: Dataset export has an intros mode
`GET /conversations/export-dataset` SHALL accept `mode=intros`, emitting one sample per user-confirmed paired voice exemplar: the identity's fact sheet as `system`, the post as `user`, the intro as `assistant`, verbatim. The mode SHALL honour `identity_id`, `list_id` and `min_outcome`, SHALL exclude exemplars flagged `held_out`, SHALL respect the export's sequence-length and auditing rules, and SHALL record the mode in the audit entry. `mode=conversations` SHALL remain the default.

#### Scenario: Intros mode
- **WHEN** the user exports with `mode=intros` and `min_outcome=replied`
- **THEN** each line is a post-and-intro pair from a confirmed exemplar whose conversation got a reply

#### Scenario: Held-out exemplar
- **WHEN** an exemplar is flagged `held_out`
- **THEN** it does not appear in the export
