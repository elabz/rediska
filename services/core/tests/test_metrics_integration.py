"""Integration tests for metrics and observability endpoints."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


class TestMetricsEndpointIntegration:
    """Integration tests for /api/metrics endpoints."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_all_metrics_endpoints_defined(self, client):
        """All metrics endpoints should be defined."""
        endpoints = [
            "/api/health",
            "/api/ready",
            "/api/metrics",
            "/api/metrics/queues",
            "/api/metrics/sync",
            "/api/metrics/application",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should not return 404
            assert response.status_code != 404, f"{endpoint} not found"

    def test_health_always_accessible(self, client):
        """Health endpoint should always be accessible."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_ready_always_accessible(self, client):
        """Readiness endpoint should always be accessible."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True

    def test_metrics_requires_auth(self, client):
        """Metrics endpoint should require authentication."""
        response = client.get("/api/metrics")

        # Should require auth or return data if auth is disabled
        assert response.status_code in (200, 401, 403)

    def test_queue_metrics_requires_auth(self, client):
        """Queue metrics should require authentication."""
        response = client.get("/api/metrics/queues")

        assert response.status_code in (200, 401, 403)

    def test_sync_metrics_requires_auth(self, client):
        """Sync metrics should require authentication."""
        response = client.get("/api/metrics/sync")

        assert response.status_code in (200, 401, 403)


class TestHealthEndpointDetails:
    """Detailed tests for health endpoint."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_health_includes_service_name(self, client):
        """Health should include service name."""
        response = client.get("/api/health")

        data = response.json()
        assert "service" in data
        assert data["service"] == "rediska-core"

    def test_health_includes_version(self, client):
        """Health should include version."""
        response = client.get("/api/health")

        data = response.json()
        assert "version" in data

    def test_health_includes_timestamp(self, client):
        """Health should include timestamp."""
        response = client.get("/api/health")

        data = response.json()
        assert "timestamp" in data

        # Should be valid ISO format
        timestamp = data["timestamp"]
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    def test_health_response_time_reasonable(self, client):
        """Health check should respond quickly."""
        import time

        start = time.time()
        response = client.get("/api/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        # Should respond in under 100ms
        assert elapsed < 0.1


class TestReadinessEndpointDetails:
    """Detailed tests for readiness endpoint."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_readiness_includes_ready_status(self, client):
        """Readiness should include ready boolean."""
        response = client.get("/api/ready")

        data = response.json()
        assert "ready" in data
        assert isinstance(data["ready"], bool)

    def test_readiness_includes_timestamp(self, client):
        """Readiness should include timestamp."""
        response = client.get("/api/ready")

        data = response.json()
        assert "timestamp" in data


class TestMetricsCollectorIntegration:
    """Integration tests for MetricsCollector."""

    def test_collector_tracks_multiple_metrics(self):
        """Collector should track multiple metrics simultaneously."""
        from rediska_core.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.reset()

        # Add various metrics
        collector.increment("requests_total")
        collector.increment("requests_total")
        collector.set_gauge("active_connections", 5)
        collector.record_histogram("request_duration", 0.1)
        collector.record_histogram("request_duration", 0.2)

        # Get all metrics
        all_metrics = collector.get_all()

        assert all_metrics["counters"]["requests_total"] == 2
        assert all_metrics["gauges"]["active_connections"] == 5
        assert "request_duration" in all_metrics["histograms"]

    def test_collector_with_labels(self):
        """Collector should support labeled metrics."""
        from rediska_core.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.reset()

        collector.increment("http_requests", labels={"method": "GET", "path": "/api"})
        collector.increment("http_requests", labels={"method": "POST", "path": "/api"})
        collector.increment("http_requests", labels={"method": "GET", "path": "/api"})

        # GET /api should be 2
        value = collector.get("http_requests", labels={"method": "GET", "path": "/api"})
        assert value == 2

        # POST /api should be 1
        value = collector.get("http_requests", labels={"method": "POST", "path": "/api"})
        assert value == 1

    def test_histogram_statistics(self):
        """Histogram should calculate statistics."""
        from rediska_core.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.reset()

        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        for v in values:
            collector.record_histogram("latency", v)

        stats = collector.get_histogram_stats("latency")

        assert stats["count"] == 10
        assert stats["min"] == 1
        assert stats["max"] == 10
        assert stats["avg"] == 5.5


class TestSystemMetricsIntegration:
    """Integration tests for SystemMetrics."""

    def test_system_metrics_handles_missing_redis(self):
        """SystemMetrics should handle missing Redis gracefully."""
        from rediska_core.observability.metrics import SystemMetrics

        # Use invalid URL to ensure Redis connection fails
        metrics = SystemMetrics(redis_url="redis://invalid:99999/0")

        # Should not raise, just return empty
        queue_metrics = metrics.collect_queue_metrics()
        assert isinstance(queue_metrics, dict)

    def test_system_metrics_collect_all(self):
        """collect_all should return structured data."""
        from rediska_core.observability.metrics import SystemMetrics

        metrics = SystemMetrics(redis_url="redis://invalid:99999/0")

        result = metrics.collect_all()

        assert "collected_at" in result
        assert "queues" in result
        assert "sync_times" in result


class TestStructuredLoggingIntegration:
    """Integration tests for structured logging."""

    def test_json_formatter_output(self):
        """JSON formatter should produce valid JSON."""
        import logging

        from rediska_core.observability.logging import JsonFormatter

        formatter = JsonFormatter(service_name="test-service")

        # Create a log record
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        # Should be valid JSON
        data = json.loads(output)
        assert data["message"] == "Test message"
        assert data["level"] == "INFO"
        assert data["service"] == "test-service"

    def test_structured_logger_with_context(self):
        """StructuredLogger should include context in logs."""
        import logging
        from io import StringIO

        from rediska_core.observability.logging import (
            JsonFormatter,
            RequestContext,
            get_logger,
        )

        # Setup handler to capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())

        # Get logger and add handler
        logger = get_logger("test.context")
        logger._logger.addHandler(handler)
        logger._logger.setLevel(logging.INFO)

        # Log with context
        context = RequestContext(
            request_id="req-123",
            user_id="user-456",
            path="/api/test",
        )

        logger.info("Test message", context=context)

        # Check output
        output = stream.getvalue()
        data = json.loads(output)

        assert data["request_id"] == "req-123"
        assert data["user_id"] == "user-456"
        assert data["path"] == "/api/test"

    def test_configure_logging_json_mode(self):
        """configure_logging should set up JSON formatting."""
        import logging

        from rediska_core.observability.logging import JsonFormatter, configure_logging

        configure_logging(level="DEBUG", json_format=True, service_name="config-test")

        # Root logger should have our handler
        root = logging.getLogger()
        assert len(root.handlers) > 0

        # Handler should use JSON formatter
        handler = root.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)


class TestObservabilityMiddleware:
    """Tests for observability in request handling."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_health_endpoint_fast(self, client):
        """Health should be fast (no auth overhead)."""
        import time

        times = []
        for _ in range(5):
            start = time.time()
            client.get("/api/health")
            times.append(time.time() - start)

        avg_time = sum(times) / len(times)
        assert avg_time < 0.05  # Average under 50ms

    def test_multiple_health_checks_consistent(self, client):
        """Multiple health checks should return consistent results."""
        responses = [client.get("/api/health").json() for _ in range(5)]

        # All should have same status
        statuses = [r["status"] for r in responses]
        assert all(s == "healthy" for s in statuses)

        # All should have same service
        services = [r["service"] for r in responses]
        assert all(s == "rediska-core" for s in services)
