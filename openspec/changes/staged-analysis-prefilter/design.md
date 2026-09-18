## Context

`MultiAgentAnalysisService._run_dimension_agents` builds five agent coroutines and awaits them with `asyncio.gather`, retries failures once, then the gates are evaluated and the meta agent runs. Both the lead API path and `scout.analyze_and_decide` call this method, so staging belongs there. A Redis inference gate with `INFERENCE_MAX_CONCURRENT=1` serialises the calls to protect the llama.cpp gateway (added after the 2026-09-16 outage, when parallel agents caused a 429 storm), so the five "parallel" agents already run back to back and staging costs no wall-clock time on posts that go the distance.

Gate dependencies: gender and location ← demographics; D/s ← sexual_preferences; age acceptance ← relationship_goals; authenticity ← risk_flags. Verdict rule: any `fail` → `not_recommended`.

Two downstream consumers assume all five dimensions ran: the calibration report treats a dimension missing from a scout post's stored results as a failure, and the UI renders five cards.

## Goals / Non-Goals

**Goals:**
- Stop spending inference on posts whose verdict is already fixed.
- Never change a verdict, and never thin what a human reviewer sees.
- Keep failure metrics honest.
- Measure before and after.

**Non-Goals:**
- Changing gates, thresholds, concurrency, or adding body-text pre-filters (see proposal).

## Decisions

**1. Two stages, split where the gate dependencies split.**
Demographics alone feeds two gates; it is also the cheapest prompt. Stage 1 = demographics, stage 2 = everything else. *Alternative:* fully sequential agents, exiting after whichever gate fails first. It would save a little more on D/s, age, and authenticity fails, but those are rarer, each needs its own agent anyway, and the code becomes a five-step state machine. Revisit with the early-exit-by-gate data this change collects.

**2. Exit on `fail` only.**
`unclear` is the state a human resolves. A reviewer looking at an unclear location needs the preferences and goals cards to decide whether the post is worth the trouble. This keeps the needs-review queue as informative as it is today.

**3. Verdict equivalence is the core invariant and gets a property test.**
For any combination of dimension outputs, `staged_verdict == evaluate_gates(all outputs).recommendation`. The test enumerates gate-relevant output combinations (each field pass / fail / unclear / missing) and asserts equality. Confidence score: an early exit computes the score from what exists, within the `not_recommended` band (0.0 to 0.3); it can differ from the full-analysis score inside that band, which no threshold reads.

**4. `skipped` is a first-class dimension status; `not_evaluated` is a first-class gate marker.**
Without them, a skipped dimension looks like a failure to the calibration report (which infers failure from absence), and its gates would read `unclear`, which is false: nobody looked. The MySQL enum gains `skipped`; scout `dimension_results_json` stores `{"skipped": true, "reason": "gender gate failed"}` so absence still means failure. `not_evaluated` only ever appears beside a `fail`, so the verdict rule is untouched.

**5. Partial gate evaluation reuses the gate functions.**
`evaluate_gates_partial(dimension_results, available={"demographics"})` calls the same `_gate_gender` and `_gate_location`. No second copy of gate logic. If `configurable-match-profile` has landed, the profile is passed the same way.

**6. Title-tag stage ships in shadow mode.**
A regex deciding a verdict with no model and no human is the most aggressive optimisation here, and tags are written by people: a couple posting as `[MF4F]`, a wrong tag, a tag describing the wanted partner. The existing demographics prompt already treats the first letter as the author's gender, so the tag rule is not new, but it has never been measured alone. Shadow mode produces exactly that measurement from live traffic at zero risk. Activation is a config change the user makes after reading the agreement number; a suggested bar is 99% agreement over at least 500 parsed posts. In active mode a passing tag never skips the demographics agent, because location and age still need it.

**7. Manual analysis is always full.**
When the user clicks analyse they are asking to see everything; saving five calls there saves little and annoys. `full=true` is also the escape hatch for any early-exited scout post, stored as a new analysis so history stays append-only.

**8. Feature flag defaults on, tag mode defaults shadow.**
`ANALYSIS_STAGED_ENABLED=false` restores today's behaviour exactly. Both variables must be added to the `docker-compose.yml` environment blocks for core and worker or they do nothing.

**9. Evaluations on early exits.**
An early-exited subject can be evaluated on the final verdict and on the demographics dimension. Evaluation controls for skipped dimensions are hidden. The stratified review queue keeps sampling `not_recommended`, so a wrong early exit (a demographics error) is exactly what reviewers will catch; the "Run full analysis" action sits next to the verdict.

## Risks / Trade-offs

- [A demographics mistake now costs the whole analysis, not just one gate] → it already fixed the verdict before; what is lost is the other cards. Mitigated by one-click full analysis, by the review queue sampling `not_recommended`, and by retrying demographics before deciding.
- [Less data for source-discovery and for prompt replay on early-exited posts] → replay counts them as skipped for the four dimensions; discovery mining uses verdicts, which are unaffected.
- [Interest vocabulary and affinity see fewer posts] → only posts that were never going to be leads are skipped; affinity is still computed (it needs no agent) if that change has landed.
- [Title tag active mode produces a wrong fail] → shadow first, strict pattern, disagreement list in the report, instant rollback by setting the mode.
- [Consumers that assume five dimensions] → audit of every reader of `dimension_results_json` and `analysis_dimensions` is an explicit task, with tests on the calibration report, evaluation queue, lead detail, and scout history.
- [Expected saving does not materialise] → task 1 measures the gender/location fail share from existing reports before any code is written; stop if it is small.

## Migration Plan

1. Measure: read gate outcome shares from the latest calibration reports.
2. Migration: enum value `skipped`, new nullable columns. Additive.
3. Ship staging behind the flag with the tag parser in shadow mode.
4. After one weekly calibration report, check savings and tag agreement.
5. Optionally switch the tag mode to `active`.
Rollback: `ANALYSIS_STAGED_ENABLED=false`; stored skipped rows remain valid history.

## Open Questions

- Should authenticity (risk_flags) move into stage 1 if its fail rate turns out to be high? Decide from the early-exit-by-gate table.
- Should an early-exited post whose author later becomes a lead through another post be auto-upgraded to a full analysis? Proposed: no, the new post gets its own analysis.
