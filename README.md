# Rediska

Local-first conversation management and lead discovery system with provider integrations.

## Quick Start

### Prerequisites
- Docker and Docker Compose v2
- Node.js 20+ (for local web development)
- Python 3.11+ (for local API development)
- mkcert (recommended for local TLS)

### 1. Clone and Configure

```bash
git clone <repository-url>
cd rediska

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# At minimum, set strong passwords for MySQL
```

### 2. Generate TLS Certificates

Using mkcert (recommended):
```bash
# Install mkcert if not already installed
# macOS: brew install mkcert
# Linux: see https://github.com/FiloSottile/mkcert

# Install local CA
mkcert -install

# Generate certificates
mkcert -cert-file nginx/certs/tls.crt -key-file nginx/certs/tls.key rediska.local localhost 127.0.0.1
```

Or use self-signed (not recommended):
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/tls.key \
  -out nginx/certs/tls.crt \
  -subj "/CN=rediska.local"
```

### 3. Add Host Entry

```bash
# Add to /etc/hosts
echo "127.0.0.1 rediska.local" | sudo tee -a /etc/hosts
```

### 4. Create Local Storage Directories

```bash
sudo mkdir -p /var/lib/rediska/{attachments,backups}
sudo chown -R $(whoami) /var/lib/rediska
```

### 5. Start Services

```bash
docker compose up -d
```

### 6. Run Database Migrations

```bash
docker compose exec rediska-core alembic upgrade head
```

### 7. Access the Application

Open https://rediska.local in your browser.

Default credentials will be set up on first run (see bootstrap process in docs).

## Architecture

```
Browser → Nginx (HTTPS:443) → Next.js Web App → FastAPI Core → MySQL/ES/Redis
                                                    ↓
                                              Celery Worker → Providers/LLM
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| rediska-nginx | 80, 443 | Reverse proxy (only external access) |
| rediska-web | 3000 (internal) | Next.js frontend |
| rediska-core | 8000 (internal) | FastAPI backend |
| rediska-worker | - | Celery task worker |
| rediska-beat | - | Celery scheduler |
| rediska-mysql | 3306 (internal) | MySQL database |
| rediska-redis | 6379 (internal) | Redis cache/broker |
| rediska-elasticsearch | 9200 (internal) | Search engine |

## Development

### Web Frontend
```bash
cd apps/web
npm install
npm run dev
```

### Core API
```bash
cd services/core
pip install -e ".[dev]"
uvicorn rediska_core.main:app --reload
```

### Worker
```bash
cd services/worker
pip install -e ".[dev]"
celery -A rediska_worker.celery_app worker -l INFO
```

## Documentation

- [CLAUDE.md](./CLAUDE.md) - Development guide for Claude Code
- [Spec Pack](./prd/Rediska_Spec_Pack_v0.3.md) - Technical specifications
- [Sprint Plan](./prd/Rediska_Sprint_Plan_v0.1.md) - Development roadmap
- [Task Breakdown](./prd/Rediska_Task_Breakdown_v0.1.md) - Implementation checklist

## Key Principles

1. **Local Storage Only**: All data stays on your machine
2. **No Remote Deletes**: Provider deletions never remove local data
3. **No Auto-send**: All outgoing messages require explicit user action
4. **Provider Agnostic**: Core system is decoupled from specific providers

## License

Private/Proprietary
