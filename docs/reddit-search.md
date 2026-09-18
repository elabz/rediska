# Reddit search for scout watches: reliability, syntax, and cost of reading all posts

Research and measurements from 2026-09-18. It answers three questions:

- Is Reddit search reliable enough to drive scout watches?
- What syntax limits apply?
- What would it cost to read every post instead?

The audit scripts are in `scripts/search_audit/`; see [Re-running the audit](#re-running-the-audit). Re-run them before drawing new conclusions: subreddit volumes and posting habits change.

## TL;DR

- **Reddit search did not lose posts.** On all 6 watches, search returned exactly the posts that a local check of the full `/new` feed said should match: 0 misses and 0 unexpected results.
- **Recall was lost in the queries themselves:**
  - tag variants that are different words to the search engine (`F4Any` ≠ `F4A`, `F4R`, couples written `MF4M` as well as `FM4M`);
  - location wording (only `PA/NJ/PHILA/PHILLY`).
- **Fixed on 2026-09-18** by expanding the queries of all watches ([current queries](#current-watch-queries)). On the same data, r/dirtyr4r went from about 4 to about 15 matching posts/day, and r/bdsmpersonals from about 14 to about 18.
- **Reading every post** (`/new` + a cheap tag filter + full analysis) would take analysis from ~20 to ~225 posts/day. LLM time and the Reddit API budget can absorb that; the real cost is ~90 needs-review posts/day of human triage. Build it only together with staged analysis (demographics first, early exit on a clear gender or location fail).

## Search syntax and limits

Sources:
- Reddit Help, "Available search features" (updated 2026-09-16): <https://support.reddithelp.com/hc/en-us/articles/19696541895316>
- API docs: <https://www.reddit.com/dev/api/#GET_search>
- Data API wiki (rate limits): <https://support.reddithelp.com/hc/en-us/articles/16160319875092>

Claims marked *measured* were confirmed against our own data.

| Topic | Finding |
|---|---|
| Operators | `AND`, `OR`, `NOT` are **case-sensitive and must be uppercase**; lowercase `and` is searched as a word. Parentheses group. `-term` is not documented; use `NOT`. |
| Implicit operator | For **post** search, bare terms are loose-OR ("results only need to include some of your search words"). **Always write explicit `AND`/`OR` and parenthesise groups.** |
| Query length | `q` ≤ **512 characters** (API docs). No documented limit on the number of OR alternatives or on nesting. *Measured*: a 13-way OR group ANDed with a 10-way OR group (212 chars) matched local evaluation exactly. |
| Case | Case-insensitive (*measured*: `F4M` finds `[f4m]`). |
| Tokenization | Behaves like alphanumeric runs; brackets and `#` are ignored (*measured*). **No splitting inside codes**: `F4M` does not match `FM4M`, `F4A` does not match `F4Any`, and `29F4M` would be the single token `29f4m`. Each variant must be listed explicitly. |
| Field operators | `title:`, `selftext:`, `author:`, `flair:`, `self:true/false`, `site:`, `url:`, `subreddit:` (no space after the colon). `nsfw:yes` / `flair_name:` are not documented today. |
| Index lag | No primary source. *Measured*: no misses even among posts under 2 h old. |
| NSFW | `/search` got NSFW subreddits' posts without `include_over_18` (*measured*: 0 misses on NSFW subs). |
| Result depth | Listings stop at ~1000 items. |
| Rate limit | 100 requests/min per OAuth client (1000 per 10 min). A search costs one request, the same as a listing page. |

## Measurement 1: search vs. the full feed

Method (`search_audit.py`):
1. Fetch `/r/{sub}/new` (~1000 posts).
2. Evaluate each watch's boolean query locally on title+body tokens.
3. Run the watch's search over the same window (a week, or ~12 h for r/dirtyr4r, where 1000 posts is ~12 h).
4. Compare the two sets of post IDs.

| Watch | Posts/day | Should match | Search returned | Missed |
|---|---|---|---|---|
| r/bdsmpersonals | 125 | 99 | 99 | 0 |
| r/spanking_personals | 8 | 4 | 4 | 0 |
| r/dirtyr4r | 2,029 | 3 | 3 | 0 |
| r/R4R30Plus | 51 | 4 | 4 | 0 |
| r/R4R40Plus | 21 | 0 | 0 | 0 |
| r/agegappersonals | 79 | 1 | 1 | 0 |

r/bdsmpersonals: 712 of 873 posts in the window had an empty body (link-only weheartbdsm.com listings), so search there effectively matches titles only. The listing content is resolved after fetch; see External Listing Resolution in [CLAUDE.md](../CLAUDE.md).

## Measurement 2: where recall was lost

Method (`search_audit2.py`): a tolerant title-code regex (brackets, spacing, glued ages, any case) classifies each post. "Target" means the poster includes a woman (F, FM/MF, TF…) and seeks a man, anyone, redditors, or a couple.

Target posts/day missed by the old queries' `(F4M OR F4A)`:

| Form | Where | Per day |
|---|---|---|
| `F4Any` | r/bdsmpersonals | 3.3 |
| `F4R` | r/R4R30Plus, r/R4R40Plus | 3.4 |
| `MF4M` 8.1, `MF4A` 6.1, `MF4MF` 4.1, `FM4A` 4.1 | r/dirtyr4r | ~22 |
| `TF4A` 8.1, `MTF4M` 6.1 (trans women; **not** added, by decision) | r/dirtyr4r | ~14 |

- Couples write the order both ways, and `MF4M` is more common than `FM4M`, so every couple code is listed in both orders.
- No-code titles are rare (~5/day across all 6 subreddits).

**Location** (r/dirtyr4r, target posts only): `PA/NJ/PHILA/PHILLY` caught ~6/day. An extended in-range list caught ~18/day. The remaining target posts were overwhelmingly tagged with far-away places or "online".

## Current watch queries

Applied 2026-09-18 to watches 1–6. Each change is recorded in `audit_log` as `scout_watch.update` with the previous query.

Gender clause (all watches):

```
(F4M OR F4A OR F4Any OR F4R OR F4MF OR FM4M OR MF4M OR FM4A OR MF4A OR FM4FM OR MF4MF OR FM4MF OR MF4FM)
```

Location clause (r/dirtyr4r, r/R4R30Plus, r/R4R40Plus, r/agegappersonals), ANDed with the gender clause:

```
(PA OR NJ OR PHILA OR PHILLY OR Philadelphia OR Pennsylvania OR Jersey OR Delaware OR NYC OR Baltimore)
```

Verification before switching (`verify_queries.py`, same windows):

| Watch | Old matches/day | New matches/day | Search misses | Old matches still included |
|---|---|---|---|---|
| r/bdsmpersonals | 14.1 | 17.6 | 0 | yes |
| r/spanking_personals | 0.6 | 0.6 | 0 | yes |
| r/dirtyr4r | 4.1 | 14.5 | 0 | yes |
| r/R4R30Plus | 0.6 | 1.4 | 0 | yes |
| r/R4R40Plus | 0 | 0 | 0 | yes |
| r/agegappersonals | 0.1 | 0.3 | 0 | yes (search returned 1 extra post) |

**Adding terms later:**
- Keep the whole query under 512 characters (currently 212).
- Operators stay uppercase.
- List every variant spelling as its own term.
- Adding a term cannot drop posts, but it adds LLM work: each extra match is a full analysis (~34–60 s).

## Reading every post instead: cost

The idea: poll `/r/{sub}/new` every 5 minutes, drop obviously unsuitable posts with a regex tag filter (no LLM), and fully analyse the rest, including borderline posts with no tag.

| | Now (search) | Read all + tag filter |
|---|---|---|
| New posts, all 6 subreddits | — | ~2,300/day (r/dirtyr4r ~2,030) |
| Kept by the tag filter | — | ~220/day, plus ~5/day with no tag |
| Posts analysed | ~20/day | **~225/day (~11×)** |
| LLM time (sum of call time; the gate runs `INFERENCE_MAX_CONCURRENT`=2 at once here, so wall-clock is roughly half) | ~20 min/day | **~2.5–4 h/day** |
| Reddit API calls | ~1,700/day | ~3,100/day (~2% of the 144k/day budget) |
| needs_review to triage (41% of analysed) | ~8/day | **~90/day** |
| suitable (7% of analysed) | ~1–2/day | ~15/day |

Basis:
- One synthetic 6-agent run took 34 s of LLM time (5 dimension agents 25 s, meta 9 s). Real runs add 2 summary calls and larger inputs, and one measured real reanalysis took ~60 s.
- Polling `/new` costs the same number of requests as searching. The extra calls come from author lookups (~3 per analysed post).
- Recommendation rates are from scout posts analysed 2026-09-04 to 2026-09-18.

Caveats:
- ~158 of r/dirtyr4r's ~176 target posts/day are far away. Without staged analysis each costs a full run just to fail the location gate. With demographics-first early exit (the `staged-analysis-prefilter` change), each costs ~8 s instead of ~60 s.
- `/new` holds only the last ~1000 posts, ~12 h for r/dirtyr4r. A worker outage longer than that can only be back-filled with search.
- Reposts barely inflate volume: distinct target authors per day ≈ target posts per day.

## Regional personals subreddits (PA/NJ/DE/MD/NY)

Found 2026-09-18 by combining two sources. First, Reddit subreddit search for ~30 regional personals queries ("philadelphia r4r", "nj hookup", "baltimore r4r", "nyc personals"…). Second, community names in our authors' stored history that contain a regional term.

A name regex alone is too loose ("pa" matches *pasta*, *pawg*), so the list was curated by hand. It excludes:
- places beyond the ~200-mile radius (Pittsburgh, Buffalo, Albany, upstate NY);
- photo-only "gonewild" subreddits;
- paid-content and findom subreddits;
- orientation-specific subreddits.

48 were added as `manual` source candidates, visible in the Discover tab; filter by name with "r4r", "nj", "philly" and so on:

- **PA:** pennsylvaniadirtyr4r, pahookups, paswingers, pennsylvaniar4r, philadelphiar4r, philadelphiabetterr4r, newphillyhookups, philly4anonfun, pa4r, pennsylvaniansa, lancasterswingers, scranton_hookups, harrisburgdungeon
- **NJ:** nj4nj, njr4r, r4r_nj, njstraightr4r, njr4rstraight, nj_swingers, nj_lifestyle, njhotwife, jerseyshoredlfwb, newjerseyfwb_fun, nj4smash
- **DE:** delawarer4r
- **MD/DC:** baltimoreanddcr4r, marylandr4r, marylandswingersr4r, dmvcasualencounters, dmvbaddiesndaddies
- **NYC/LI:** nyr4r, nycr4r, r4rnyc, nychookups_, nychookups, hookupsnewyork, newyorkhookingup, newyorkhookups, r4rnychookups, nyfwb, nyc_fuckbuddy, newyorkswingers, newyorkswingersr4r, newyorkswingersclub, nyhotwifes, newyorkr4r, longislandsingles_, longislandswing (plus longislandhookups, already a candidate)

**Workflow:** Preview search → Run trial → Create watch. Location-specific subreddits may not need the location clause, so edit the pre-filled query when creating the watch.

## Community rules that forbid contact

Some communities forbid approaching posters, for example "No personals", "This is not a dating sub", "No asking for DMs". The Discover tab flags them with the quoted rule and hides them by default.

The check is a conservative pattern match (`contact_restriction()` in `source_discovery.py`), tuned against real rules. Personals subreddits commonly carry rules that must *not* flag:
- "No personal info"
- "No solicitation" (in hookup subreddits this means sex work)
- "No unsolicited nudes/DMs"
- "No seeking relationships for others"

First run, 2026-09-18: 35 of ~260 communities flagged, and a manual review found them correct. The one partial case is r/polyamoryr4r ("strictly not a hookup reddit" — relationship posts are fine there).

## Re-running the audit

The scripts only read (Reddit listings and search, plus the `scout_watches` table). They print counts and title tags only, never post text. Each run costs ~60–120 Reddit requests.

```bash
docker cp scripts/search_audit/search_audit.py  rediska-worker:/tmp/search_audit.py
docker cp scripts/search_audit/search_audit2.py rediska-worker:/tmp/search_audit2.py
docker cp scripts/search_audit/verify_queries.py rediska-worker:/tmp/verify_queries.py
docker compose exec -T rediska-worker python /tmp/search_audit.py    # search vs /new per watch
docker compose exec -T rediska-worker python /tmp/search_audit2.py   # tag variants, location, volumes
docker compose exec -T rediska-worker python /tmp/verify_queries.py  # check candidate queries before switching
```

`search_audit2.py` and `verify_queries.py` load helpers from `/tmp/search_audit.py`, so copy all three. The candidate queries to verify are hard-coded in `verify_queries.py` (`NEW_QUERIES`); edit them before checking a new set.
