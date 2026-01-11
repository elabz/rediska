"""Metrics API routes for observability."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from rediska_core.api.deps import get_current_user
from rediska_core.observability.metrics import MetricsCollector, SystemMetrics, get_collector

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint (public, no auth required).

    Returns basic health status of the service.
    """
    return {
        "status": "healthy",
        "service": "rediska-core",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def readiness_check() -> dict[str, Any]:
    """Readiness check endpoint (public, no auth required).

    Returns whether the service is ready to accept requests.
    Checks database and other dependencies.
    """
    # TODO: Add actual dependency checks (DB, Redis, etc.)
    return {
        "ready": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics")
async def get_metrics(
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all metrics (requires authentication).

    Returns collected metrics including:
    - Application metrics (counters, gauges, histograms)
    - System metrics (queue depths, sync times)
    """
    collector = get_collector()
    system_metrics = SystemMetrics()

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "application": collector.get_all(),
        "system": system_metrics.collect_all(),
    }


@router.get("/metrics/queues")
async def get_queue_metrics(
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get queue depth metrics (requires authentication).

    Returns current depth of each Celery queue.
    """
    system_metrics = SystemMetrics()
    return system_metrics.collect_queue_metrics()


@router.get("/metrics/sync")
async def get_sync_metrics(
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get sync time metrics (requires authentication).

    Returns last sync time for each provider.
    """
    system_metrics = SystemMetrics()
    return system_metrics.collect_sync_times()


@router.get("/metrics/application")
async def get_application_metrics(
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get application-level metrics (requires authentication).

    Returns counters, gauges, and histograms collected by the application.
    """
    collector = get_collector()
    return collector.get_all()
