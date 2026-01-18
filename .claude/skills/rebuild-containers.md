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

## Notes

- Use `--no-cache` to ensure fresh builds
- The worker depends on core being healthy, so restart order matters
- Check logs after restart to verify no startup errors
