"""Metrics collection for Rediska services.

Provides simple metrics collection for monitoring:
- Counters: Monotonically increasing values
- Gauges: Point-in-time values
- Histograms: Distribution of values
"""

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MetricType(Enum):
    """Types of metrics."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """A single metric value.

    Attributes:
        name: Metric name
        type: Type of metric (counter, gauge, histogram)
        value: Current value
        labels: Optional labels for metric dimensions
        timestamp: When the metric was recorded
    """

    name: str
    type: MetricType
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Set default timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert metric to dictionary.

        Returns:
            Dictionary representation of the metric
        """
        return {
            "name": self.name,
            "type": self.type.value,
            "value": self.value,
            "labels": self.labels,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class MetricsCollector:
    """Thread-safe metrics collector.

    Collects and stores metrics in memory for later retrieval.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._lock = threading.RLock()  # Use RLock to allow reentrant locking
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    def _make_key(self, name: str, labels: Optional[dict[str, str]] = None) -> str:
        """Create a unique key for a metric with labels.

        Args:
            name: Metric name
            labels: Optional labels

        Returns:
            Unique key string
        """
        if not labels:
            return name

        # Sort labels for consistent key generation
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Increment a counter metric.

        Args:
            name: Counter name
            value: Value to add (default 1)
            labels: Optional labels
        """
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Set a gauge metric value.

        Args:
            name: Gauge name
            value: Current value
            labels: Optional labels
        """
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def record_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a value in a histogram.

        Args:
            name: Histogram name
            value: Value to record
            labels: Optional labels
        """
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)

    def get(
        self,
        name: str,
        labels: Optional[dict[str, str]] = None,
    ) -> float:
        """Get a metric value.

        Args:
            name: Metric name
            labels: Optional labels

        Returns:
            Metric value, or 0 if not found
        """
        key = self._make_key(name, labels)
        with self._lock:
            if key in self._counters:
                return self._counters[key]
            if key in self._gauges:
                return self._gauges[key]
            return 0

    def get_histogram_stats(
        self,
        name: str,
        labels: Optional[dict[str, str]] = None,
    ) -> dict[str, float]:
        """Get histogram statistics.

        Args:
            name: Histogram name
            labels: Optional labels

        Returns:
            Dictionary with count, min, max, avg, p50, p95, p99
        """
        key = self._make_key(name, labels)
        with self._lock:
            values = self._histograms.get(key, [])

        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0}

        sorted_values = sorted(values)
        count = len(values)

        return {
            "count": count,
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "avg": sum(values) / count,
            "p50": sorted_values[int(count * 0.5)],
            "p95": sorted_values[min(int(count * 0.95), count - 1)],
            "p99": sorted_values[min(int(count * 0.99), count - 1)],
        }

    def get_all(self) -> dict[str, Any]:
        """Get all metrics as a dictionary.

        Returns:
            Dictionary with all metrics
        """
        with self._lock:
            result = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: self.get_histogram_stats(k)
                    for k in self._histograms.keys()
                },
            }
        return result

    def reset(self) -> None:
        """Reset all metrics to zero."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


class SystemMetrics:
    """System-level metrics collection.

    Collects metrics about queues, sync status, and other system health.
    """

    # Queue names to monitor
    QUEUE_NAMES = ["ingest", "index", "embed", "agent", "maintenance"]

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize system metrics.

        Args:
            redis_url: Optional Redis URL (defaults to env var)
        """
        self._redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._redis_client = None

    def _get_redis(self):
        """Get Redis client (lazy initialization).

        Returns:
            Redis client or None if unavailable
        """
        if self._redis_client is not None:
            return self._redis_client

        try:
            import redis
            self._redis_client = redis.from_url(self._redis_url)
            return self._redis_client
        except Exception:
            return None

    def collect_queue_metrics(self) -> dict[str, int]:
        """Collect queue depth metrics.

        Returns:
            Dictionary mapping queue names to depths
        """
        result = {}
        client = self._get_redis()

        if client is None:
            return result

        for queue_name in self.QUEUE_NAMES:
            try:
                # Celery queue key format
                key = f"celery:{queue_name}"
                depth = client.llen(key)
                result[f"queue_depth_{queue_name}"] = depth
            except Exception:
                result[f"queue_depth_{queue_name}"] = 0

        return result

    def collect_sync_times(self) -> dict[str, Optional[str]]:
        """Collect last sync times for providers.

        Returns:
            Dictionary mapping provider names to last sync times
        """
        result = {}
        client = self._get_redis()

        if client is None:
            return result

        try:
            # Look for sync time keys
            keys = client.keys("rediska:last_sync:*")
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                provider = key.split(":")[-1]
                value = client.get(key)
                if isinstance(value, bytes):
                    value = value.decode()
                result[f"last_sync_{provider}"] = value
        except Exception:
            pass

        return result

    def collect_all(self) -> dict[str, Any]:
        """Collect all system metrics.

        Returns:
            Dictionary with all system metrics
        """
        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "queues": self.collect_queue_metrics(),
            "sync_times": self.collect_sync_times(),
        }


# Global metrics collector instance
_collector = MetricsCollector()


def get_collector() -> MetricsCollector:
    """Get the global metrics collector.

    Returns:
        MetricsCollector instance
    """
    return _collector
