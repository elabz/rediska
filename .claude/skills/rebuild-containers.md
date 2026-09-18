# Rebuild Containers

Rebuild and restart Docker containers for the Rediska project.

## Usage

```
/rebuild-containers [service...]
```

If no services specified, rebuilds core and worker (most common).

## Common Services

- `rediska-core` - FastAPI backend
- `rediska-worker` - Celery worker
- `rediska-web` - Next.js frontend
- `rediska-beat` - Celery beat scheduler

## Execution Steps

### 1. Rebuild the container(s)

```bash
# For specific services
docker compose build --no-cache <service1> <service2>

# For all services
docker compose build --no-cache
```

### 2. Restart the container(s)

```bash
docker compose up -d <service1> <service2>
```

### 3. Verify they're running

```bash
docker compose ps
```

### 4. Check logs for startup errors

```bash
docker compose logs --tail=10 <service>
```

## Examples

### Rebuild core and worker (most common after Python changes)
```bash
docker compose build --no-cache rediska-core rediska-worker && docker compose up -d rediska-core rediska-worker
```

### Rebuild web (after frontend changes)
```bash
docker compose build --no-cache rediska-web && docker compose up -d rediska-web
```

### Rebuild everything
```bash
docker compose build --no-cache && docker compose up -d
```

## CRITICAL: a restart is NOT enough for the worker

**Neither** of the worker's bind mounts in `docker-compose.override.yml`
(`/app/rediska_core`, `/app/rediska_worker`) has any effect. The worker's
Dockerfile sets `WORKDIR /app/worker`, so:

| Service | `rediska_core` from | `rediska_worker` from | Picks up source edits? |
|---|---|---|---|
| `rediska-core` | `/app/rediska_core` (bind mount) | n/a | Yes — `uvicorn --reload` |
| `rediska-worker` | site-packages (mount shadowed) | `/app/worker/...` (baked, cwd wins) | **No — neither package** |
| `rediska-beat` | baked image | baked image | **No — has NO source mounts at all** |

So after editing `services/core` **or `services/worker`**, the worker keeps
running **stale code baked into its image** even though the new file is visible
at `/app`. Celery has no hot-reload. The failure is silent: core runs new code,
worker runs old code, and nothing errors.

**Always rebuild core AND worker together** after any change to either
`services/core` or `services/worker` — never just `up -d`/`restart`.

### Don't forget `rediska-beat`

`rediska-beat` runs from the **same `rediska-worker` image** but
`docker-compose.override.yml` gives it **no source mounts whatsoever** — only
`attachments` and `backups`. Confirm any time with:

```bash
docker inspect rediska-beat --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

It is therefore *more* stale-prone than the worker, and it is the process that
dispatches every scheduled task — so anything touching `celery_app.py`
(`beat_schedule`, `task_routes`) or the task modules needs beat rebuilt and
recreated too:

```bash
docker compose build rediska-core rediska-worker && \
  docker compose up -d rediska-core rediska-worker rediska-beat
```

Observed 2026-09-17: fixing dead `task_routes` patterns had no effect on
scheduled work until `rediska-beat` was rebuilt — the worker alone was not
enough.

Observed 2026-07-20: a new `maintenance.merge_duplicate_author_leads` task,
committed 11 hours earlier, was simply **absent** from the running worker —
`hasattr(module, 'merge_duplicate_author_leads')` was `False`. Nothing in the
logs indicated a problem.

### Verify the rebuild actually took

Do not assume. Assert on the **specific symbol you just added**, not on generic
health — a stale worker starts fine and looks healthy:

```bash
docker compose exec -T rediska-worker python -c "
import rediska_worker.tasks.<module> as m
print('worker symbol:', hasattr(m, '<new_function>'))
from rediska_core.domain.services.<svc> import <Class>
print('core symbol:', hasattr(<Class>, '<new_method>'))
"
```

Both must print `True`. Note that `app.tasks` registration is lazy — importing
`celery_app` alone will report a new task as missing even on fresh code; import
the task module explicitly before checking, or call
`app.loader.import_default_modules()` to populate the whole registry at once.

Changed queue routing? Assert no task falls through to the default queue:

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.celery_app import app
app.loader.import_default_modules()
default = app.conf.task_default_queue or 'celery'
bad = [n for n in app.tasks if not n.startswith('celery.')
       and getattr(app.amqp.router.route({}, n).get('queue'), 'name', None) == default]
print('registered:', len([n for n in app.tasks if not n.startswith('celery.')]))
print('on default queue:', bad or 'NONE')
"
```

`task_routes` patterns match **registered task names** (`ingest.*`), never module
paths — a `rediska_worker.tasks.<module>.*` glob silently matches nothing. Core API
`send_task` calls all pass `queue=` explicitly, so only beat and worker-internal
dispatches depend on these routes.

## After restarting the worker: clear the inference gate slot

LLM calls go through a cross-process Redis semaphore (`rediska:inference:inflight`).
A worker process killed mid-request leaves its slot counted for up to
`INFERENCE_TIMEOUT+120`s, during which analyses stall on gate waits. Always run this
right after `docker compose up -d rediska-worker`:

```bash
docker compose exec -T rediska-redis redis-cli del rediska:inference:inflight
```

Avoid rebuilding while a re-analysis batch is running (see `reanalyze-scout-posts.md`):
in-flight tasks die on the time limit and must be re-queued.

## Notes

- Plain `docker compose build` is normally sufficient — source is `COPY`'d, so a
  cache-busting `--no-cache` is rarely needed and costs several minutes
- The worker depends on core being healthy, so restart order matters
- Check logs after restart to verify no startup errors
- `rediska-web` always needs a real rebuild (no hot-reload in the container)
- Adding a new setting to `config.py`? It also has to be added to the
  `environment:` blocks in `docker-compose.yml` or it will never reach the
  containers — see the `compose-env-wiring` project memory
- Changed a value in `.env`? No rebuild, but `docker compose restart` does **not**
  re-read it — only `docker compose up -d <svc>` (recreate) does. Verify by hashing the
  var inside the container vs `.env` (never print it). `rediska-beat` has no
  `INFERENCE_*` vars by design.
- Recreating a container discards its logs. If you need a failure's log evidence
  (e.g. a "JSON parse error … Context around" line), pull it *before* rebuilding.
