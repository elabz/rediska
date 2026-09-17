"""Unit tests for observability features (structured logging, metrics)."""

import json
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from rediska_core.observability.logging import (
    StructuredLogger,
    JsonFormatter,
    RequestContext,
    get_logger,
    configure_logging,
)
from rediska_core.observability.metrics import (
    MetricsCollector,
    MetricType,
    Metric,
    SystemMetrics,
)


class TestJsonFormatter:
    """Tests for JSON log formatter."""

    def test_format_basic_log_record(self):
        """Test formatting a basic log record to JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert "timestamp" in parsed

    def test_format_log_with_extra_fields(self):
        """Test formatting log record with extra fields."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.user_id = "user-123"
        record.request_id = "req-456"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["user_id"] == "user-123"
        assert parsed["request_id"] == "req-456"

    def test_format_log_with_exception(self):
        """Test formatting log record with exception info."""
        formatter = JsonFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_format_log_with_message_args(self):
        """Test formatting log record with message arguments."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="User %s performed action %s",
            args=("alice", "login"),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "User alice performed action login"

    def test_timestamp_is_iso_format(self):
        """Test that timestamp is in ISO format."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        # Must actually round-trip through the ISO parser, and carry the
        # UTC offset JsonFormatter attaches via tz=timezone.utc.
        parsed_ts = datetime.fromisoformat(parsed["timestamp"])
        assert parsed_ts.utcoffset() == timedelta(0)


class TestRequestContext:
    """Tests for request context management."""

    def test_create_context(self):
        """Test creating a request context."""
        context = RequestContext(
            request_id="req-123",
            user_id="user-456",
            path="/api/test",
            method="GET",
        )

        assert context.request_id == "req-123"
        assert context.user_id == "user-456"
        assert context.path == "/api/test"
        assert context.method == "GET"

    def test_context_to_dict(self):
        """Test converting context to dictionary."""
        context = RequestContext(
            request_id="req-123",
            user_id="user-456",
        )

        result = context.to_dict()

        assert result["request_id"] == "req-123"
        assert result["user_id"] == "user-456"

    def test_context_with_extra_data(self):
        """Test context with additional data."""
        context = RequestContext(
            request_id="req-123",
            extra={"identity_id": "id-789", "provider": "reddit"},
        )

        result = context.to_dict()

        assert result["identity_id"] == "id-789"
        assert result["provider"] == "reddit"


def capture_structured_logger(name: str, level: int = logging.DEBUG):
    """Attach a JsonFormatter StringIO handler to a fresh StructuredLogger.

    Returns (logger, read) where read() parses the single emitted JSON record.
    """
    buffer = StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())

    logger = StructuredLogger(name)
    logger._logger.handlers.clear()
    logger._logger.addHandler(handler)
    logger._logger.setLevel(level)
    # Don't let records escape to the root logger's handlers.
    logger._logger.propagate = False

    def read():
        return json.loads(buffer.getvalue().strip())

    return logger, read


class TestStructuredLogger:
    """Tests for structured logger."""

    def test_create_logger(self):
        """Test creating a structured logger."""
        logger = StructuredLogger("test.module")

        assert logger.name == "test.module"

    def test_log_info_message(self):
        """Test logging an info message."""
        logger, read = capture_structured_logger("test.log.info")

        logger.info("Test info message")

        parsed = read()
        assert parsed["message"] == "Test info message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.log.info"

    def test_log_with_context(self):
        """Test logging with request context."""
        logger, read = capture_structured_logger("test.log.context")
        context = RequestContext(
            request_id="req-123", user_id="user-456", path="/api/test"
        )

        logger.info("Test message", context=context)

        parsed = read()
        # Context fields are flattened onto the record by _log().
        assert parsed["request_id"] == "req-123"
        assert parsed["user_id"] == "user-456"
        assert parsed["path"] == "/api/test"

    def test_log_with_extra_fields(self):
        """Test logging with extra fields."""
        logger, read = capture_structured_logger("test.log.extra")

        logger.info("User action", user_id="user-123", action="login")

        parsed = read()
        assert parsed["message"] == "User action"
        assert parsed["user_id"] == "user-123"
        assert parsed["action"] == "login"

    def test_log_error_with_exception(self):
        """Test logging error with exception."""
        logger, read = capture_structured_logger("test.log.error")

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.error("Error occurred", exc_info=True)

        parsed = read()
        assert parsed["level"] == "ERROR"
        assert "ValueError: Test error" in parsed["exception"]
        # WARNING and above also get a source location block, and it must point
        # at the real call site rather than StructuredLogger's own wrapper --
        # _log passes stacklevel=3 to walk back past itself and error().
        assert parsed["source"]["function"] == "test_log_error_with_exception"
        assert parsed["source"]["file"].endswith("test_observability_unit.py")

    def test_log_warning(self):
        """Test logging a warning."""
        logger, read = capture_structured_logger("test.log.warning")

        logger.warning("Warning message", code="W001")

        parsed = read()
        assert parsed["level"] == "WARNING"
        assert parsed["message"] == "Warning message"
        assert parsed["code"] == "W001"

    def test_log_debug(self):
        """Test logging a debug message."""
        logger, read = capture_structured_logger("test.log.debug")

        logger.debug("Debug details", data={"key": "value"})

        parsed = read()
        assert parsed["level"] == "DEBUG"
        assert parsed["data"] == {"key": "value"}


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_structured_logger(self):
        """Test that get_logger returns a StructuredLogger."""
        logger = get_logger("test.module")

        assert isinstance(logger, StructuredLogger)

    def test_get_logger_same_name_returns_same_instance(self):
        """Test that same name returns same logger instance."""
        logger1 = get_logger("test.same")
        logger2 = get_logger("test.same")

        assert logger1 is logger2

    def test_get_logger_different_names(self):
        """Test that different names return different loggers."""
        logger1 = get_logger("test.one")
        logger2 = get_logger("test.two")

        assert logger1.name != logger2.name


class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_logging_sets_level(self):
        """Test that configure_logging sets the log level."""
        configure_logging(level="DEBUG")

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        # configure_logging replaces handlers wholesale with a single one.
        assert len(root.handlers) == 1
        assert root.handlers[0].level == logging.DEBUG

    def test_configure_logging_json_format(self):
        """Test configuring JSON format logging."""
        configure_logging(json_format=True)

        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_configure_logging_non_json_format(self):
        """Test that json_format=False installs a plain text formatter."""
        configure_logging(json_format=False)

        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert not isinstance(formatter, JsonFormatter)
        assert isinstance(formatter, logging.Formatter)

    def test_configure_logging_with_service_name(self):
        """Test configuring logging with service name."""
        configure_logging(service_name="rediska-core")

        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, JsonFormatter)
        # The service name must reach the formatter so it lands in every record.
        assert formatter.service_name == "rediska-core"

        record = logging.LogRecord(
            name="test.service", level=logging.INFO, pathname="t.py",
            lineno=1, msg="hi", args=(), exc_info=None,
        )
        assert json.loads(formatter.format(record))["service"] == "rediska-core"


class TestMetricType:
    """Tests for MetricType enum."""

    def test_counter_type(self):
        """Test counter metric type."""
        assert MetricType.COUNTER.value == "counter"

    def test_gauge_type(self):
        """Test gauge metric type."""
        assert MetricType.GAUGE.value == "gauge"

    def test_histogram_type(self):
        """Test histogram metric type."""
        assert MetricType.HISTOGRAM.value == "histogram"


class TestMetric:
    """Tests for Metric dataclass."""

    def test_create_counter_metric(self):
        """Test creating a counter metric."""
        metric = Metric(
            name="requests_total",
            type=MetricType.COUNTER,
            value=100,
            labels={"endpoint": "/api/inbox"},
        )

        assert metric.name == "requests_total"
        assert metric.type == MetricType.COUNTER
        assert metric.value == 100

    def test_create_gauge_metric(self):
        """Test creating a gauge metric."""
        metric = Metric(
            name="queue_depth",
            type=MetricType.GAUGE,
            value=42,
            labels={"queue": "ingest"},
        )

        assert metric.name == "queue_depth"
        assert metric.value == 42

    def test_metric_to_dict(self):
        """Test converting metric to dictionary."""
        metric = Metric(
            name="sync_duration_seconds",
            type=MetricType.GAUGE,
            value=3.5,
            labels={"provider": "reddit"},
        )

        result = metric.to_dict()

        assert result["name"] == "sync_duration_seconds"
        assert result["type"] == "gauge"
        assert result["value"] == 3.5
        assert result["labels"]["provider"] == "reddit"

    def test_metric_with_timestamp(self):
        """Test metric with timestamp."""
        now = datetime.now(timezone.utc)
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            value=1,
            timestamp=now,
        )

        assert metric.timestamp == now


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_increment_counter(self):
        """Test incrementing a counter."""
        collector = MetricsCollector()

        collector.increment("requests_total", labels={"endpoint": "/api/test"})
        collector.increment("requests_total", labels={"endpoint": "/api/test"})

        value = collector.get("requests_total", labels={"endpoint": "/api/test"})
        assert value == 2

    def test_set_gauge(self):
        """Test setting a gauge value."""
        collector = MetricsCollector()

        collector.set_gauge("queue_depth", 42, labels={"queue": "ingest"})

        value = collector.get("queue_depth", labels={"queue": "ingest"})
        assert value == 42

    def test_set_gauge_overwrites(self):
        """Test that setting gauge overwrites previous value."""
        collector = MetricsCollector()

        collector.set_gauge("active_connections", 10)
        collector.set_gauge("active_connections", 5)

        value = collector.get("active_connections")
        assert value == 5

    def test_record_histogram(self):
        """Test recording histogram values."""
        collector = MetricsCollector()

        collector.record_histogram("request_duration", 0.5)
        collector.record_histogram("request_duration", 1.0)
        collector.record_histogram("request_duration", 0.3)

        stats = collector.get_histogram_stats("request_duration")

        assert stats["count"] == 3
        assert stats["min"] == 0.3
        assert stats["max"] == 1.0

    def test_get_all_metrics(self):
        """Test getting all metrics."""
        collector = MetricsCollector()

        collector.increment("counter_a")
        collector.increment("counter_a")
        collector.set_gauge("gauge_b", 10)
        collector.record_histogram("hist_c", 2.5)

        metrics = collector.get_all()

        # get_all() always returns the three buckets, so assert the contents.
        assert metrics["counters"] == {"counter_a": 2}
        assert metrics["gauges"] == {"gauge_b": 10}
        assert metrics["histograms"]["hist_c"]["count"] == 1
        assert metrics["histograms"]["hist_c"]["max"] == 2.5

    def test_get_nonexistent_metric_returns_zero(self):
        """Test getting non-existent metric returns 0."""
        collector = MetricsCollector()

        value = collector.get("nonexistent")

        assert value == 0

    def test_reset_metrics(self):
        """Test resetting all metrics."""
        collector = MetricsCollector()

        collector.increment("test_counter")
        collector.set_gauge("test_gauge", 10)
        collector.reset()

        assert collector.get("test_counter") == 0
        assert collector.get("test_gauge") == 0


class TestSystemMetrics:
    """Tests for system metrics collection."""

    def test_collect_queue_metrics(self):
        """Test collecting queue depth metrics."""
        metrics = SystemMetrics()

        # Mock Redis connection
        mock_redis = MagicMock()
        mock_redis.llen.return_value = 42

        with patch.object(metrics, "_get_redis", return_value=mock_redis):
            queue_metrics = metrics.collect_queue_metrics()

        # One queue_depth_<name> entry per monitored queue, keyed by name.
        assert set(queue_metrics) == {
            f"queue_depth_{name}" for name in SystemMetrics.QUEUE_NAMES
        }
        assert all(depth == 42 for depth in queue_metrics.values())
        # Depth is read from the Celery list key for each queue.
        mock_redis.llen.assert_any_call("celery:ingest")

    def test_collect_queue_metrics_without_redis(self):
        """Queue metrics degrade to an empty dict when Redis is unavailable."""
        metrics = SystemMetrics()

        with patch.object(metrics, "_get_redis", return_value=None):
            assert metrics.collect_queue_metrics() == {}

    def test_collect_last_sync_times(self):
        """Test collecting last sync times."""
        metrics = SystemMetrics()

        mock_redis = MagicMock()
        # collect_sync_times() scans for keys first; without this the iteration
        # over a bare MagicMock raises and the result is silently empty.
        mock_redis.keys.return_value = [b"rediska:last_sync:reddit"]
        mock_redis.get.return_value = b"2024-01-15T12:00:00Z"

        with patch.object(metrics, "_get_redis", return_value=mock_redis):
            sync_times = metrics.collect_sync_times()

        # Provider is the last colon-segment; bytes are decoded on both sides.
        assert sync_times == {"last_sync_reddit": "2024-01-15T12:00:00Z"}
        mock_redis.keys.assert_called_once_with("rediska:last_sync:*")

    def test_collect_all_metrics(self):
        """Test collecting all system metrics."""
        metrics = SystemMetrics()

        with patch.object(metrics, "_get_redis", return_value=None):
            all_metrics = metrics.collect_all()

        assert set(all_metrics) == {"collected_at", "queues", "sync_times"}
        # Parseable ISO timestamp, not just a present key.
        assert datetime.fromisoformat(all_metrics["collected_at"]).tzinfo is not None
        # No Redis -> both sub-collections degrade to empty, not missing.
        assert all_metrics["queues"] == {}
        assert all_metrics["sync_times"] == {}


class TestLoggingIntegration:
    """Integration tests for logging system."""

    def test_json_logging_output(self):
        """Test that logging produces valid JSON output."""
        # Create a string buffer to capture log output
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(JsonFormatter())

        logger = logging.getLogger("test.integration")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test integration message")

        output = buffer.getvalue()
        # Should be valid JSON
        parsed = json.loads(output.strip())
        assert parsed["message"] == "Test integration message"

    def test_structured_logger_with_json_handler(self):
        """Test structured logger with JSON handler."""
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(JsonFormatter())

        logger = StructuredLogger("test.structured")
        logger._logger.addHandler(handler)
        logger._logger.setLevel(logging.INFO)

        logger.info("Structured test", request_id="req-123")

        output = buffer.getvalue()
        parsed = json.loads(output.strip())
        assert "request_id" in parsed


class TestMetricsIntegration:
    """Integration tests for metrics system."""

    def test_metrics_collector_thread_safety(self):
        """Test that metrics collector is thread-safe."""
        import threading

        collector = MetricsCollector()
        errors = []

        def increment_counter():
            try:
                for _ in range(100):
                    collector.increment("concurrent_counter")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=increment_counter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert collector.get("concurrent_counter") == 1000

    def test_metrics_to_json(self):
        """Test that metrics can be serialized to JSON."""
        collector = MetricsCollector()

        collector.increment("test_counter")
        collector.set_gauge("test_gauge", 42)

        metrics = collector.get_all()
        # Should be JSON serializable
        json_output = json.dumps(metrics)
        assert json_output is not None
