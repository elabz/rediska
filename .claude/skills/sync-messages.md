# Sync Messages

Trigger message sync from Reddit to fetch new conversations and messages.

## Usage

```
/sync-messages [--full]
```

- `--full` - Run full backfill instead of delta sync

## Execution Steps

### 1. Delta sync (new messages only)

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.ingest import sync_delta
result = sync_delta.delay(provider_id='reddit')
print(f'Sync task queued: {result.id}')
"
```

### 2. Full backfill (all conversations)

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.tasks.ingest import backfill_conversations
result = backfill_conversations.delay(provider_id='reddit')
print(f'Backfill task queued: {result.id}')
"
```

### 3. Monitor sync progress

```bash
# Watch the logs
docker compose logs -f rediska-worker 2>&1 | grep -E "(sync|inbox|sent|Page|messages)"
```

### 4. Check sync results

After the task completes, look for the result in logs:
```bash
docker compose logs --tail=100 rediska-worker 2>&1 | grep -E "sync_delta.*succeeded"
```

Example output:
```
Task ingest.sync_delta[...] succeeded in 45.2s: {
  'status': 'success',
  'conversations_synced': 150,
  'messages_synced': 1200,
  'new_conversations': 5,
  'new_messages': 23
}
```

## What Gets Synced

1. **Inbox messages** - Messages received from other users
2. **Sent messages** - Messages you've sent
3. **Attachments** - Images are automatically downloaded from:
   - `i.redd.it` URLs
   - `preview.redd.it` URLs
   - `matrix.redditspace.com` URLs (Reddit's new format)
   - `imgur.com` URLs

## Sync Schedule

The sync runs automatically via Celery Beat every 10 minutes. Check beat schedule:
```bash
docker compose logs --tail=20 rediska-beat
```

## Troubleshooting

### No new messages synced?
1. Check if there are actually new messages on Reddit
2. Verify OAuth tokens are valid: check for 401 errors in logs
3. Run a manual sync and watch the logs

### Attachments not downloading?
1. Check if URL patterns are being recognized
2. Look for "Failed to download" warnings in logs
3. May need to run `/dispatch-task redownload_attachments`
