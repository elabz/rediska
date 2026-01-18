# Dispatch Task

Manually dispatch a Celery task for execution.

## Usage

```
/dispatch-task <task_name> [args]
```

## Available Tasks

| Task | Queue | Description |
|------|-------|-------------|
| `ingest.sync_delta` | ingest | Sync new messages from Reddit |
| `ingest.backfill_conversations` | ingest | Full conversation import |
| `ingest.redownload_attachments` | ingest | Re-download missing images |
| `ingest.analyze_lead_profile` | ingest | Fetch profile + run analysis |
| `scout.run_all_watches` | scout | Run all active scout watches |
| `scout.run_single_watch` | scout | Run specific watch by ID |
| `message.send_manual` | messages | Send a pending message |
| `multi_agent_analysis.analyze_lead` | multi_agent_analysis | Run multi-agent analysis |

## Execution Steps

### 1. Sync messages from Reddit

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.ingest import sync_delta
result = sync_delta.delay(provider_id='reddit')
print(f'Task queued: {result.id}')
"
```

### 2. Redownload missing attachments

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.ingest import redownload_attachments
result = redownload_attachments.delay(limit=100)
print(f'Task queued: {result.id}')
"
```

### 3. Run all scout watches

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.scout import run_all_watches
result = run_all_watches.delay()
print(f'Task queued: {result.id}')
"
```

### 4. Run single scout watch

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.scout import run_single_watch
result = run_single_watch.delay(watch_id=<WATCH_ID>)
print(f'Task queued: {result.id}')
"
```

### 5. Send pending message (retry)

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.message import send_manual
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Message, Conversation

session = get_sync_session_factory()()
message = session.query(Message).filter(Message.id == <MESSAGE_ID>).first()
conv = message.conversation

payload = {
    'message_id': message.id,
    'conversation_id': conv.id,
    'identity_id': conv.identity_id,
    'provider_id': conv.provider_id,
    'body_text': message.body_text,
    'attachment_ids': [],
}

result = send_manual.apply_async(args=[payload], queue='messages')
print(f'Task dispatched: {result.id}')
session.close()
"
```

### 6. Analyze lead profile

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.ingest import analyze_lead_profile
result = analyze_lead_profile.delay(lead_id=<LEAD_ID>, run_multi_agent=True)
print(f'Task queued: {result.id}')
"
```

### 7. Run multi-agent analysis

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.multi_agent_analysis import analyze_lead
result = analyze_lead.delay(<LEAD_ID>)
print(f'Task queued: {result.id}')
"
```

## Checking Task Status

After dispatching, check worker logs:
```bash
docker compose logs --tail=30 rediska-worker 2>&1 | grep "<task_id>"
```

Or check for SUCCESS/FAILURE:
```bash
docker compose logs --tail=50 rediska-worker 2>&1 | grep -E "(SUCCESS|FAILURE)"
```
