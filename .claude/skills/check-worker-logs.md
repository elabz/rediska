# Check Worker Logs

View and filter Celery worker logs for task execution and debugging.

## Usage

```
/check-worker-logs [task_pattern] [lines]
```

- `task_pattern` - Optional grep pattern to filter (e.g., "send", "scout", "sync")
- `lines` - Number of lines to tail (default: 50)

## Execution Steps

### 1. View recent logs

```bash
docker compose logs --tail=50 rediska-worker
```

### 2. Filter for specific task types

```bash
# Send message tasks
docker compose logs --tail=100 rediska-worker 2>&1 | grep -iE "(send|message\.send)"

# Scout watch tasks
docker compose logs --tail=100 rediska-worker 2>&1 | grep -iE "(scout|watch)"

# Sync tasks
docker compose logs --tail=100 rediska-worker 2>&1 | grep -iE "(sync|ingest)"

# Multi-agent analysis
docker compose logs --tail=100 rediska-worker 2>&1 | grep -iE "(multi_agent|analyze_lead)"

# Task success/failure
docker compose logs --tail=100 rediska-worker 2>&1 | grep -iE "(SUCCESS|FAILURE|ERROR)"
```

### 3. Follow logs in real-time

```bash
docker compose logs -f rediska-worker
```

### 4. Check for specific message/task ID

```bash
docker compose logs --tail=200 rediska-worker 2>&1 | grep -i "<message_id_or_task_id>"
```

## Common Patterns

| Pattern | What it shows |
|---------|---------------|
| `send_manual` | Message sending tasks |
| `sync_delta` | Message sync from Reddit |
| `scout` | Scout watch monitoring |
| `analyze` | Lead analysis tasks |
| `SUCCESS` | Completed tasks |
| `FAILURE\|ERROR` | Failed tasks |
| `received` | Tasks picked up by worker |

## Troubleshooting

### Task not executing?
1. Check if worker is running: `docker compose ps rediska-worker`
2. Check active queues: `docker compose exec rediska-worker celery -A rediska_worker.celery_app inspect active_queues`
3. Check Redis queue: `docker compose exec rediska-redis redis-cli -n 1 KEYS "*"`

### Task failing?
Look for the full error message:
```bash
docker compose logs --tail=200 rediska-worker 2>&1 | grep -A5 "FAILURE\|ERROR\|Exception"
```
