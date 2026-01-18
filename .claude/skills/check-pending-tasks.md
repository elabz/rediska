# Check Pending Tasks

Query the database for pending messages, jobs, and task status.

## Usage

```
/check-pending-tasks [type]
```

- `type` - Optional: `messages`, `jobs`, `all` (default: all)

## Execution Steps

### 1. Check pending outbound messages

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Message, Conversation, ExternalAccount

session = get_sync_session_factory()()

pending = session.query(Message).filter(
    Message.direction == 'out',
    Message.remote_visibility == 'unknown'
).order_by(Message.created_at.desc()).limit(10).all()

print(f'Found {len(pending)} pending outbound messages:')
for m in pending:
    conv = m.conversation
    counterpart = conv.counterpart_account.external_username if conv and conv.counterpart_account else 'Unknown'
    print(f'  ID: {m.id}, To: {counterpart}, Created: {m.created_at}')
    print(f'    Body: {m.body_text[:60] if m.body_text else \"(empty)\"}...')

session.close()
"
```

### 2. Check pending jobs

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Job

session = get_sync_session_factory()()

pending = session.query(Job).filter(
    Job.status.in_(['queued', 'running', 'retrying'])
).order_by(Job.id.desc()).limit(10).all()

print(f'Found {len(pending)} pending jobs:')
for job in pending:
    print(f'  ID: {job.id}, Type: {job.job_type}, Status: {job.status}, Queue: {job.queue_name}')
    if job.last_error:
        print(f'    Error: {job.last_error[:60]}...')

session.close()
"
```

### 3. Check failed jobs

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Job

session = get_sync_session_factory()()

failed = session.query(Job).filter(
    Job.status == 'failed'
).order_by(Job.id.desc()).limit(10).all()

print(f'Found {len(failed)} failed jobs:')
for job in failed:
    print(f'  ID: {job.id}, Type: {job.job_type}')
    print(f'    Error: {job.last_error[:80] if job.last_error else \"No error\"}...')

session.close()
"
```

### 4. Check Redis queue lengths

```bash
docker compose exec -T rediska-redis redis-cli -n 1 KEYS "*" | while read key; do
  len=$(docker compose exec -T rediska-redis redis-cli -n 1 LLEN "$key" 2>/dev/null)
  if [ -n "$len" ] && [ "$len" != "0" ]; then
    echo "$key: $len"
  fi
done
```

## Common Issues

### Messages stuck in "Pending"
1. Check if associated job exists and its status
2. Check worker logs for errors
3. May need to retry: see `/dispatch-task` skill

### Jobs stuck in "queued"
1. Check if worker is consuming from the right queue
2. Check `docker compose exec rediska-worker celery -A rediska_worker.celery_app inspect active_queues`
