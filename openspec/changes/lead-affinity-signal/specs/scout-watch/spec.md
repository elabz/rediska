## ADDED Requirements

### Requirement: Needs-review queue can be ordered by affinity

Analysed scout posts SHALL store the affinity score and explanation computed at analysis time. `GET /scout-watches/needs-review` SHALL accept `sort=affinity`, ordering untriaged `needs_review` posts by affinity descending with nulls last and then newest first, using a keyset cursor consistent with that ordering. The default ordering SHALL remain newest first. Affinity SHALL NOT remove any post from the queue.

#### Scenario: Near-misses that resemble past successes surface first

- **WHEN** the user sorts the needs-review queue by affinity
- **THEN** posts most similar to previously contacted or engaged leads are listed first and every untriaged post is still reachable by paging

#### Scenario: Default unchanged

- **WHEN** no sort is requested
- **THEN** the queue is newest first, exactly as before
