# Database Query

Run ad-hoc database queries against the Rediska MySQL database.

## Usage

```
/db-query <description of what to find>
```

## Execution Method

Use Python with SQLAlchemy through the core container:

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import <Model>

session = get_sync_session_factory()()

# Your query here
result = session.query(<Model>).filter(...).all()

# Process results
for item in result:
    print(f'...')

session.close()
"
```

## Common Queries

### Get recent messages

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Message

session = get_sync_session_factory()()
messages = session.query(Message).order_by(Message.sent_at.desc()).limit(10).all()

for m in messages:
    print(f'{m.id}: {m.direction} - {m.sent_at} - {m.body_text[:50] if m.body_text else \"\"}'...)

session.close()
"
```

### Get lead by ID

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Lead

session = get_sync_session_factory()()
lead = session.query(Lead).filter(Lead.id == <LEAD_ID>).first()

if lead:
    print(f'Lead {lead.id}:')
    print(f'  Title: {lead.title}')
    print(f'  Author: {lead.author_account.external_username if lead.author_account else \"Unknown\"}')
    print(f'  Status: {lead.status}')
    print(f'  Created: {lead.created_at}')
else:
    print('Lead not found')

session.close()
"
```

### Get conversation with messages

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import Conversation, Message

session = get_sync_session_factory()()
conv = session.query(Conversation).filter(Conversation.id == <CONV_ID>).first()

if conv:
    print(f'Conversation {conv.id} with {conv.counterpart_account.external_username}')
    messages = session.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.sent_at).all()
    for m in messages:
        direction = '→' if m.direction == 'out' else '←'
        print(f'  {direction} {m.sent_at}: {m.body_text[:60] if m.body_text else \"\"}...')

session.close()
"
```

### Check scout watches

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import ScoutWatch

session = get_sync_session_factory()()
watches = session.query(ScoutWatch).all()

print(f'Found {len(watches)} scout watches:')
for w in watches:
    status = 'ACTIVE' if w.is_active else 'inactive'
    print(f'  {w.id}: {w.source_location} [{status}]')
    print(f'       Query: {w.search_query or \"(none)\"}')

session.close()
"
```

### Get recent scout runs

```bash
docker compose exec -T rediska-core python -c "
from rediska_core.infra.db import get_sync_session_factory
from rediska_core.domain.models import ScoutWatchRun

session = get_sync_session_factory()()
runs = session.query(ScoutWatchRun).order_by(ScoutWatchRun.started_at.desc()).limit(10).all()

print(f'Recent scout runs:')
for r in runs:
    status = 'OK' if not r.error_message else 'ERROR'
    print(f'  {r.id}: Watch {r.watch_id} @ {r.started_at} [{status}]')
    print(f'       Fetched: {r.posts_fetched}, New: {r.posts_new}, Leads: {r.leads_created}')

session.close()
"
```

## Available Models

- `Message` - Chat messages
- `Conversation` - Chat threads
- `ExternalAccount` - Reddit users
- `Identity` - Your Reddit identities
- `Lead` - Saved leads from posts
- `LeadAnalysis` - Multi-agent analysis results
- `ScoutWatch` - Watch configurations
- `ScoutWatchRun` - Watch execution history
- `ScoutWatchPost` - Posts found by watches
- `Job` - Celery job tracking
- `Attachment` - File attachments
- `ProfileSnapshot` - User profile summaries
