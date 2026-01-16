FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy core package first and install it
COPY core/ /app/core/
RUN pip install --no-cache-dir /app/core

# Copy worker package and install it
COPY worker/ /app/worker/
RUN pip install --no-cache-dir /app/worker

# Set working directory to worker
WORKDIR /app/worker

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["celery", "-A", "rediska_worker.celery_app", "worker", "-l", "INFO", "-Q", "celery,ingest,index,embed,agent,maintenance,messages,multi_agent_analysis,scout"]
