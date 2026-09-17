# Re-analyze Scout Posts in Bulk

Re-run the analysis pipeline over a set of already-seen scout watch posts (after an
inference outage, a prompt/parser/gate change, or a schema fix) and watch it drain.
Worked out 2026-09-16 while recovering from the LiteLLM 429 outage.

## Usage

```
/reanalyze-scout-posts <selection-sql-where-clause>
```

## Execution Steps

### 1. Pick the posts with SQL (never the inbox tables)

```bash
cd /Users/boss/Web/rediska
docker compose exec -T rediska-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -N -e "
SELECT watch_id, id, external_post_id FROM scout_watch_posts
WHERE analysis_status=\"analyzed\" AND lead_id IS NULL
  AND first_seen_at >= \"2026-09-09\"
  AND JSON_SEARCH(dimension_results_json, \"one\", \"%dimension missing or failed%\") IS NOT NULL
ORDER BY first_seen_at DESC;"' > /tmp/reanalyze.tsv
wc -l /tmp/reanalyze.tsv
```

Useful predicates: `"%dimension missing or failed%"` (verdicts made while agents were
failing), `analysis_recommendation="needs_review"`, `watch_id=1` (r/bdsmpersonals).
Posts by already-contacted authors are skipped by STEP 0 of the task (cheap, no LLM).

### 2. Enqueue once, from inside the worker

```bash
docker cp /tmp/reanalyze.tsv rediska-worker:/tmp/reanalyze.tsv
docker compose exec -T rediska-worker python -c "
from rediska_worker.celery_app import app
n=0
for line in open('/tmp/reanalyze.tsv'):
    w, pid, ext = line.split()
    app.send_task('scout.reanalyze_post', kwargs={'watch_id': int(w), 'post_id': int(pid), 'external_post_id': ext}, queue='scout'); n+=1
print('queued', n)"
```

**Do not re-enqueue "failed" posts after every restart** — each blanket re-queue added
duplicate copies (up to 4x the same post). If you must add posts, dedupe first (step 5).

### 3. Expect this throughput

- Full analysis = ~7 LLM calls (2 summaries + 5 dimensions + advisory meta) at ~20-50 s
  each on the Pascal cards, i.e. **~5 min wall time per post per slot**.
- `INFERENCE_MAX_CONCURRENT` (in `.env`, default 1) is the real throughput knob; it is a
  cross-process gate, so 4 worker processes still share it. With 3 NSFW replicas, 2 is
  safe. ~2 posts/min at 2 slots when most posts are real analyses.
- The 5-minute `scout.run_all_watches` beat keeps enqueueing `run_single_watch` ×6 into
  the same `scout` queue; they back up behind long analyses. Harmless, but dedupe them
  (step 5) before they turn into dozens of redundant Reddit searches.

### 4. Watch it

```bash
docker compose exec -T rediska-redis redis-cli -n 1 llen scout          # queue depth
L=$(docker compose logs --since 1h rediska-worker 2>&1)
echo "$L" | grep -c 'scout.reanalyze_post\[.*succeeded'                # completions
echo "$L" | grep -c "'lead_created': True"; echo "$L" | grep -c "'lead_attached': True"
echo "$L" | grep -c '429 Too Many'; echo "$L" | grep -c SoftTimeLimitExceeded
echo "$L" | grep -oE 'slot acquired after [0-9.]+s' | tail -3           # gate waits
docker compose exec -T rediska-redis redis-cli get rediska:inference:inflight
```

`docker compose logs --since` takes local time or epoch seconds — a UTC timestamp
silently returns nothing. A recreated container's log starts empty, so count from the
broker queue, not from log lines, across restarts.

Verdict/gate breakdown for a set of ids:

```bash
docker compose exec -T rediska-mysql sh -c 'mysql ... -N -e "SELECT analysis_recommendation,
JSON_EXTRACT(dimension_results_json, \"$.gate_verdict.gate_results\") FROM scout_watch_posts WHERE id IN (...)"'
```
then tally `status != pass` entries per gate in Python (`location=far`, `age_acceptance`
partner-age caps, `ds_compatibility`, `dimension missing or failed`, `field missing`).

### 5. Dedupe the queue in place (safe, transactional)

```bash
docker compose exec -T rediska-worker python - <<'PY'
import json, base64, os, redis
r = redis.Redis.from_url(os.environ["CELERY_BROKER_URL"])
def key_of(raw):
    m = json.loads(raw); t = m["headers"].get("task")
    args, kw = json.loads(base64.b64decode(m["body"]))[:2]
    if t == "scout.reanalyze_post": return (t, kw.get("external_post_id"))
    if t == "scout.run_single_watch": return (t, kw.get("watch_id") or (args[0] if args else None))
    if t == "scout.run_all_watches": return (t,)
    return (t, m["headers"].get("id"))
for _ in range(5):
    with r.pipeline() as p:
        try:
            p.watch("scout"); items = p.lrange("scout", 0, -1)   # head=newest .. tail=oldest
            seen, keep = set(), []
            for raw in reversed(items):
                k = key_of(raw)
                if k not in seen: seen.add(k); keep.append(raw)
            keep.reverse(); p.multi(); p.delete("scout")
            if keep: p.rpush("scout", *keep)
            p.execute(); print(len(items), "->", len(keep)); break
        except redis.WatchError: pass
PY
```

Celery's Redis transport is LPUSH/BRPOP, so oldest is at the tail; the rewrite keeps
that order.

### 6. If you must rebuild/restart the worker mid-batch

Killed processes leak their inference slot. Right after `docker compose up -d`:

```bash
docker compose exec -T rediska-redis redis-cli del rediska:inference:inflight
```

Then re-queue **only** the posts whose `analysis_status='failed'` (they died with
`SoftTimeLimitExceeded` or mid-fetch), and dedupe. Prefer finishing the batch before
rebuilding; the running batch will not pick up new code.

## Single post or single lead, synchronously (debugging / user asks for "a fresh LLM call")

Runs inline through the inference gate; ~5 min. Output goes to your terminal, not the
worker log (the worker's `logger` lines are swallowed by the exec), so capture what you
need with prints. Used 2026-09-16.

```bash
# One scout post — the task needs all three ids; 'skipped' means the pre-pipeline
# author gate fired (author already a lead / contacted / ignored), not a failure.
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.scout import reanalyze_post
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import ScoutWatchPost
db=get_sync_session_factory()(); p=db.get(ScoutWatchPost, <post_id>)
args=[p.watch_id, p.id, p.external_post_id]; db.close()
print(reanalyze_post.apply(args=args).get())"

# One lead — same thing the UI's Re-analyze button does; regenerates summaries only if
# the lead has none (pass regenerate_summaries=True to force).
docker compose exec -T rediska-core python -c "
import asyncio
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.config import get_settings
from rediska_core.domain.services.inference import get_inference_client
from rediska_core.domain.services.agent_prompt import AgentPromptService
from rediska_core.domain.services.multi_agent_analysis import MultiAgentAnalysisService
db=get_sync_session_factory()()
svc=MultiAgentAnalysisService(db=db, inference_client=get_inference_client(),
    prompt_service=AgentPromptService(db), chat_template=get_settings().inference_chat_template)
a=asyncio.run(svc.analyze_lead(<lead_id>))
print(a.id, a.final_recommendation, a.confidence_score, a.recommendation_reasoning[:300])"
```

Before trusting a re-run, check the lead actually has a body: leads created by manual
scout promotion before 2026-09-16 have `body_text=NULL`, and the agents then see only
the title (verdicts like "not authentic" follow from that). Backfill from the scout
post's `post_body` first.
