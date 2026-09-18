## Why

The system's purpose is finding contacts with similar, configurable interests, but what counts as a match is fixed in three unrelated places: the preferred hobbies and kinks are typed into the preferences prompt text, the accepted genders are a Python literal in `lead_gates.py`, and the user's age, D/s orientation, and home location are environment variables that need a container restart. Changing what the system looks for means editing a prompt, editing code, and editing `.env`. Worse, the prompt asks the LLM to apply a scoring rule ("2+ preferred kinks → 0.9"), so the number that drives lead priority is model arithmetic: not reproducible, not explainable, and only changeable through a prompt replay cycle.

## What Changes

- **A versioned match profile stored in the database** holds every matching criterion: weighted interests (label, category, weight, aliases), deal-breakers, accepted genders, the user's own age and D/s orientation, home coordinates and near radius, an optional author age range, and the scoring thresholds. One profile is active; every save creates a new version; any version can be restored.
- **Gates read the profile.** The gender gate passes genders in the profile's accepted list and fails other recognised genders. Age, D/s, and location gates take their constraints from the profile. Two optional gates are added, both off in the seeded profile: `author_age` (author's stated age outside the range fails) and `deal_breaker` (an extracted interest or criterion matching a profile deal-breaker fails). All gates stay fail-closed.
- **The preferences agent extracts only; Python scores.** The preferences prompt stops listing preferred interests and stops computing `compatibility_score`. After extraction, code matches extracted hobbies and kinks against the profile's interests (case-insensitive, alias-aware) and computes the compatibility score deterministically from the matched weights. The matched interests, their weights, and the profile version are stored with the analysis. **BREAKING** for edited preferences prompts: a model-reported `compatibility_score` is ignored.
- **Every analysis records the profile version** it was judged under, next to the prompt versions, on `lead_analyses` and on analysed scout posts, so evaluations and the calibration report can be segmented by profile version.
- **Preview before saving.** Because extraction output is stored, a profile edit can be replayed over recent analyses with no LLM call. The settings page shows how many recent verdicts and priority tiers would change before the user saves.
- **Settings page** `/settings/match-profile` for editing, version history, restore, and preview; API under `/match-profile`; every mutation writes `audit_log`.
- **Seeding keeps behaviour stable.** Migration seeds version 1 from the current environment values, the current code literals, and the preferred lists in the default preferences prompt. The `USER_AGE`, `USER_DS_ORIENTATION`, `HOME_LATITUDE`, `HOME_LONGITUDE`, and `LOCATION_NEAR_THRESHOLD_MILES` variables become seed-only.
- **Lead cards show why.** The lead list and detail show the matched interests behind the compatibility badge.

## Non-goals

- No per-identity profiles. One active profile for the single user; the schema leaves room for an `identity_id` later.
- No fuzzy or embedding-based interest matching. This change matches exactly on labels and aliases; semantic matching is the separate `interest-normalization` change.
- No automatic re-judging of stored analyses. Historical `lead_analyses` rows are never rewritten; preview is read-only.
- No change to the fail-closed rule, the verdict rule, the score bands, or scout `min_confidence` semantics.
- No learning of weights from outcomes; weights are set by the user. Outcome-driven ranking is the separate `lead-affinity-signal` change.
- No content filtering: deal-breakers are the user's own matching criteria applied to verdicts, never a filter on what is ingested, stored, or displayed.

## Capabilities

### New Capabilities

- `match-profile`: the versioned profile (schema, validation, versioning, restore, seeding), deterministic interest matching and compatibility scoring, preview, the API, and the settings page.

### Modified Capabilities

- `lead-analysis`: the hard-gate requirement takes constraints and the accepted-gender list from the active match profile, and allows the two optional profile-driven gates.
- `leads`: the priority-tier requirement takes its promote and demote thresholds from the active match profile and uses the code-computed compatibility score.

## Impact

- **Database**: migration adding `match_profiles` (version, is_active, profile_json, notes, created_at) and a nullable `match_profile_version` on `lead_analyses` and `scout_watch_posts`. A new active preferences prompt version (extract-only) is created; the previous one stays for rollback.
- **Core**: new `domain/services/match_profile.py` and `interest_matching.py`; `lead_gates.py` (`UserConstraints` sourced from the profile, accepted genders, optional gates); `lead_priority.py` thresholds; `geocoding.py` home point and radius; `multi_agent_analysis.py` and `tasks/scout.py` post-processing of the preferences output (same pattern as the offline `location_near` computation); `agents/default_prompts.py`; meta-agent input gains matched interests; `prompt_replay.compare_fields` drops the fields the agent no longer emits.
- **Web**: `/settings/match-profile`, BFF proxies, matched-interest chips on lead list and detail, sidebar entry.
- **Config**: five env vars demoted to seed-only in `config.py`, `.env.example`, `docker-compose.yml`, CLAUDE.md.
- **Evaluation**: preferences-dimension evaluations made before this change judged a model-computed score; the dashboard must segment by profile version so the two are not mixed.
