FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# Download GeoNames cities500 dataset for offline geocoding
RUN mkdir -p /app/data && \
    curl -sL https://download.geonames.org/export/dump/cities500.zip -o /tmp/cities500.zip && \
    apt-get update && apt-get install -y --no-install-recommends unzip && \
    unzip /tmp/cities500.zip -d /app/data/ && \
    rm /tmp/cities500.zip && \
    apt-get purge -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy all application code first
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "rediska_core.main:app", "--host", "0.0.0.0", "--port", "8000"]
