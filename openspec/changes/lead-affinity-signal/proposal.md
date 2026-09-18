## Why

The system records what happened to every lead (ignored, contacted, engaged, dismissed from needs-review) and collects explicit human verdicts, but none of it influences which lead the user sees first. Ranking is driven only by rule-based gates and a list of interests, which cannot express "this reads like the posts I actually ended up talking to". That resemblance is learnable from data already in the system, locally, with the embeddings endpoint that hybrid search already uses. One prerequisite is missing: lead posts are not embedded today. The `lead_post` branch of the embed task is a commented-out stub, so leads are text-searchable but have no vector.

## What Changes

- **Lead posts get embeddings.** The embed task implements the `lead_post` branch (title plus resolved body, truncated to the model's context), a backfill embeds existing leads, and new leads are embedded when saved or promoted.
- **Outcome labels on exemplars.** A lead's post becomes a labelled exemplar when the user's behaviour says something about it. Positive: the author was contacted or engaged, or a human evaluation agreed with a `suitable` verdict. Negative: the lead was set to `ignored`, its needs-review post was dismissed, or a human evaluation disagreed with a `suitable` verdict. `expired` and untouched leads carry no label. Labels are kept on the Elasticsearch document and updated when the underlying state changes.
- **An affinity score per analysed post.** When a post is analysed (lead or scout post), its text is embedded once and compared with its nearest labelled exemplars. The affinity is the similarity-weighted share of positive exemplars among the nearest neighbours, from 0 to 1, stored with the three most similar exemplars as the explanation. Below a minimum number of exemplars of each label the score is null and shown as "not enough history".
- **A signal, never a verdict.** Affinity does not enter any gate, does not change the recommendation or the confidence score, is not compared with scout `min_confidence`, and never hides a lead. It appears as a badge with its explanation, as an optional sort on the Leads page, and as an optional sort on the needs-review queue so near-misses that resemble past successes surface first.
- **Proof it works before it is trusted.** The calibration report gains a table of outcome rates by affinity band, so the user can see whether high affinity actually predicts contact and engagement. A setting turns the feature off entirely.
- Content stays verbatim and local: vectors are computed by the local embeddings endpoint and stored in the local Elasticsearch.

## Non-goals

- No automatic promotion, demotion, dismissal, or expiry based on affinity, and no change to priority tiers.
- No model training, fine-tuning, or classifier; nearest-neighbour over existing vectors only.
- No use of inbox or message content. Exemplars are lead posts; outcomes are lead status, account contact/engagement state, and evaluation verdicts. Conversation text is never read.
- No person-level judgement: an exemplar is a post. A negative label on one post does not mark the author; this matches the rule that verdicts are content-scoped.
- No cloud embedding or vector service.
- No default sort change on the Leads page.

## Capabilities

### New Capabilities

- `lead-affinity`: exemplar labelling rules, affinity computation and explanation, null-below-minimum behaviour, storage, the kill switch, and the calibration table.

### Modified Capabilities

- `search-indexing`: adds the requirement that lead posts are embedded, with backfill.
- `leads`: adds affinity fields on list and detail, and the optional affinity sort.
- `scout-watch`: adds the optional affinity sort on the needs-review queue and the affinity fields on scout posts.

## Impact

- **Database**: nullable `affinity_score`, `affinity_json` (neighbours, counts, model, computed_at) on `lead_posts` and `scout_watch_posts`. No new table.
- **Elasticsearch**: additive mapping fields `outcome_label` (keyword) and `outcome_weight` on `lead_post` documents; lead documents gain `embedding`.
- **Core**: new `domain/services/lead_affinity.py`; label maintenance hooks in lead status change, contact/engagement state change, needs-review dismiss, and evaluation record; list sort and read models; calibration report table.
- **Worker**: `embed.generate` `lead_post` branch; `embed.backfill_lead_posts` and `affinity.backfill` tasks with `jobs` idempotency; affinity computed at the end of `multi_agent_analysis.analyze_lead` and `scout.analyze_and_decide`.
- **Web**: affinity badge with "similar to" popover on lead cards, lead detail, needs-review rows; sort options; calibration panel table.
- **Config**: `LEAD_AFFINITY_ENABLED`, `LEAD_AFFINITY_MIN_EXEMPLARS`, `LEAD_AFFINITY_K`, wired through `docker-compose.yml`.
- **Load**: one embedding call and one filtered kNN query per analysed post; the embeddings endpoint is not behind the inference gate.
