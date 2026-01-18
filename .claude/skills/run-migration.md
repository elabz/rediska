# Run Migration

Run Alembic database migrations for the Rediska project.

## Usage

```
/run-migration [command]
```

- `command` - Optional: `upgrade`, `downgrade`, `history`, `current` (default: upgrade head)

## Execution Steps

### 1. Check current migration status

```bash
docker compose exec -T rediska-core alembic current
```

### 2. View migration history

```bash
docker compose exec -T rediska-core alembic history --verbose
```

### 3. Upgrade to latest

```bash
docker compose exec -T rediska-core alembic upgrade head
```

### 4. Upgrade one step

```bash
docker compose exec -T rediska-core alembic upgrade +1
```

### 5. Downgrade one step

```bash
docker compose exec -T rediska-core alembic downgrade -1
```

### 6. Downgrade to specific revision

```bash
docker compose exec -T rediska-core alembic downgrade <revision_id>
```

## Creating New Migrations

### Auto-generate from model changes

```bash
docker compose exec -T rediska-core alembic revision --autogenerate -m "description of changes"
```

### Create empty migration

```bash
docker compose exec -T rediska-core alembic revision -m "description"
```

## Migration Files Location

```
services/core/alembic/versions/
```

## Common Issues

### "Target database is not up to date"
Run `alembic upgrade head` first before creating new migrations.

### "Can't locate revision"
Check if migration files exist in `alembic/versions/`. May need to rebuild core container.

### Migration failed
1. Check the error message
2. Manually fix the issue in the database if needed
3. Consider creating a new migration to fix the data

## After Running Migrations

Restart the core and worker containers to pick up schema changes:
```bash
docker compose up -d rediska-core rediska-worker
```
