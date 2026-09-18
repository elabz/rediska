## ADDED Requirements

### Requirement: Matching criteria live in one versioned match profile

The system SHALL store all lead-matching criteria in a `match_profiles` record: a list of interests (each with label, category `kink` | `hobby` | `other`, weight in (0, 1], and optional aliases), a list of deal-breakers (label and optional aliases), accepted genders, the user's own age, the user's D/s orientation, home latitude/longitude, the near radius in miles, an optional author age range, which optional gates are enabled, the compatibility base value, and the priority promote and demote thresholds. Exactly one version SHALL be active. Saving SHALL create a new version and activate it; earlier versions SHALL be retained and restorable, and restoring SHALL create a new version copying the chosen one. The profile SHALL be validated on save: weights within range, labels unique case-insensitively across interests and aliases, accepted genders drawn from the recognised set, coordinates and radius plausible, and demote threshold below promote threshold.

#### Scenario: Saving creates a new active version

- **WHEN** the user saves an edited profile while version 4 is active
- **THEN** version 5 is stored and active, version 4 is retained, and an `audit_log` row records the change

#### Scenario: Invalid profile is rejected

- **WHEN** a save contains two interests whose labels or aliases collide, or a weight of 0
- **THEN** the save is rejected with a validation error naming the field and no version is created

#### Scenario: Restore

- **WHEN** the user restores version 2 while version 5 is active
- **THEN** version 6 is created with version 2's content and becomes active

### Requirement: The first profile is seeded from current behaviour

On first startup after migration, when no profile exists, the system SHALL create version 1 from the values in effect at that moment: `USER_AGE`, `USER_DS_ORIENTATION`, `HOME_LATITUDE`, `HOME_LONGITUDE`, `LOCATION_NEAR_THRESHOLD_MILES`, accepted genders `female` and `non-binary`, the preferred hobbies and kinks of the default preferences prompt with seed weights, optional gates disabled, and the existing priority thresholds. After a profile exists those environment variables SHALL NOT influence analysis, and the application SHALL log once at startup when an environment value differs from the active profile.

#### Scenario: Behaviour is unchanged at migration

- **WHEN** the migration has run and no profile edit has been made
- **THEN** a post that was `suitable` with priority `high` under the previous code receives the same recommendation and priority tier under the seeded profile

#### Scenario: Environment no longer overrides

- **WHEN** `USER_AGE` is changed in the environment after a profile exists
- **THEN** the age gate still uses the profile's age and a startup log line reports the difference

### Requirement: Interest matching and the compatibility score are computed in code

The preferences agent SHALL only extract the author's hobbies, kinks, lifestyle, and evidence. After extraction, code SHALL match each extracted term against the active profile's interest labels and aliases (case-insensitive, whitespace- and punctuation-normalised, whole-term or whole-word match) and SHALL compute `compatibility_score = 1 - (1 - base) × Π(1 - weight)` over the distinct matched interests, rounded to three decimals. The matched interests with their weights, the unmatched extracted terms, and the profile version SHALL be stored in the preferences dimension result. A `compatibility_score` reported by the model SHALL be ignored. When the preferences dimension failed, the compatibility score SHALL be null and SHALL contribute nothing to the confidence score.

#### Scenario: Same extraction, same score

- **WHEN** the same extracted terms are scored twice under the same profile version
- **THEN** the compatibility score and matched interests are identical

#### Scenario: Alias match

- **WHEN** the profile has interest "rope" with alias "shibari" and the agent extracts "Shibari"
- **THEN** "rope" is reported as matched once, with its weight

#### Scenario: No matches yields the base value

- **WHEN** no extracted term matches any profile interest
- **THEN** the compatibility score equals the profile's base value

#### Scenario: Model-reported score is ignored

- **WHEN** an edited or rolled-back preferences prompt makes the model return `compatibility_score: 0.95` with no matching interests
- **THEN** the stored compatibility score is the code-computed base value

### Requirement: Analyses record the profile version they were judged under

Every multi-agent analysis, from the API and from scout, SHALL store the active match profile version with the analysis, alongside the prompt versions. Evaluation rows SHALL snapshot it, and the evaluation summary and calibration report SHALL be able to group by it.

#### Scenario: Version recorded

- **WHEN** an analysis completes while profile version 5 is active
- **THEN** the stored analysis carries `match_profile_version = 5`

#### Scenario: Historical analyses

- **WHEN** an analysis predates this capability
- **THEN** its profile version is null and it is reported under "before match profile"

### Requirement: A profile edit can be previewed against recent analyses

`POST /match-profile/preview` SHALL accept an unsaved profile and recompute, without any LLM call, the gate verdict, compatibility score, and priority tier for the most recent analysed subjects (default 200, cap 1000) from their stored dimension outputs. It SHALL return counts of subjects whose recommendation changed, grouped by from → to, counts whose priority tier changed, and up to 20 example subjects per group. Preview SHALL NOT modify any analysis, lead, scout post, or profile.

#### Scenario: Widening accepted genders

- **WHEN** a preview adds a gender to the accepted list
- **THEN** the response reports how many recent `not_recommended` subjects would become `suitable` or `needs_review`, with examples, and nothing is persisted

#### Scenario: Subjects without stored extraction

- **WHEN** a recent subject has no stored preferences extraction
- **THEN** it is counted as "not recomputable" rather than guessed

### Requirement: Match profile API and settings page

The core SHALL expose `GET /match-profile` (active), `PUT /match-profile` (save as new version), `GET /match-profile/versions`, `POST /match-profile/versions/{version}/restore`, and `POST /match-profile/preview`. Save and restore SHALL write `audit_log` (`match_profile.save`, `match_profile.restore`) including the before and after versions. The web app SHALL provide `/settings/match-profile` with editors for interests (add, remove, reweight, aliases, category), deal-breakers, accepted genders, own age and orientation, home location and radius, optional gates, and thresholds; a preview panel; and version history with restore. The page SHALL have loading, empty, and error states and SHALL be reachable from the sidebar.

#### Scenario: Edit, preview, save

- **WHEN** the user adds an interest, runs preview, and saves
- **THEN** the preview shows the affected counts, the save creates a new version, and subsequent analyses use it

#### Scenario: Core unavailable

- **WHEN** the page cannot load the profile
- **THEN** it shows an error state with retry and never an empty editor that could overwrite the profile

### Requirement: Matched interests are visible on leads

The lead list and lead detail SHALL show the matched interests behind the compatibility badge, and the lead detail SHALL show the unmatched extracted terms.

#### Scenario: Lead card explains its score

- **WHEN** a lead has compatibility 0.89 from two matched interests
- **THEN** its card names those two interests
