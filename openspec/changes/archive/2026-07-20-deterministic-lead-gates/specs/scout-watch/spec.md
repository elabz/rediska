# scout-watch Specification (delta)

## MODIFIED Requirements

### Requirement: Auto-promotion to leads by confidence

When an analyzed post's **code-computed** recommendation is `suitable` and its **code-computed** confidence score is greater than or equal to the watch's `min_confidence`, the system SHALL automatically create a lead with `lead_source='scout_watch'` linked back to the scout post. Model-reported confidence SHALL NOT be used for promotion. Posts whose recommendation is `needs_review` or `not_recommended`, or whose computed score is below the threshold, remain in history without a lead, with their per-gate results visible.

#### Scenario: High-scoring suitable post becomes a lead

- **WHEN** the gate evaluator yields `suitable` with a computed score ≥ `min_confidence` for a watch with auto-analyze on
- **THEN** a `lead_posts` row with `lead_source='scout_watch'` is created and linked to the scout post

#### Scenario: needs_review never auto-promotes

- **WHEN** the gate evaluator yields `needs_review` for a post, regardless of its computed score
- **THEN** no lead is created automatically
- **AND** the post remains in watch history with its per-gate reasons, available for manual add-to-leads
