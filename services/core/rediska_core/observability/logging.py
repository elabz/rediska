"""Structured logging for Rediska services.

Provides JSON-formatted logging with request context support
for easier debugging and log aggregation.
"""

import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# Cache for logger instances
_loggers: dict[str, "StructuredLogger"] = {}

# Default configuration
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SERVICE_NAME = "rediska"


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Formats log records as JSON for easier parsing and analysis.
    """

    # Fields to exclude from extra data
    RESERVED_FIELDS = {
        "name", "msg", "args", "created", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs",
        "pathname", "process", "processName", "relativeCreated",
        "stack_info", "exc_info", "exc_text", "thread", "threadName",
        "message", "asctime",
    }

    def __init__(self, service_name: str = DEFAULT_SERVICE_NAME):
        """Initialize JSON formatter.

        Args:
            service_name: Name of the service for log identification
        """
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of the log record
        """
        # Build base log entry
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        # Add source location for errors
        if record.levelno >= logging.WARNING:
            log_entry["source"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_FIELDS and not key.startswith("_"):
                try:
                    # Ensure value is JSON serializable
                    json.dumps(value)
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        return json.dumps(log_entry)


@dataclass
class RequestContext:
    """Context for request-scoped logging.

    Provides a way to attach request-specific information
    to all log messages within a request.
    """

    request_id: Optional[str] = None
    user_id: Optional[str] = None
    identity_id: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary for logging.

        Returns:
            Dictionary with all context fields
        """
        result = {}

        if self.request_id:
            result["request_id"] = self.request_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.identity_id:
            result["identity_id"] = self.identity_id
        if self.path:
            result["path"] = self.path
        if self.method:
            result["method"] = self.method

        # Add extra fields
        result.update(self.extra)

        return result


class StructuredLogger:
    """Structured logger with context support.

    Wraps the standard logging module with support for
    structured fields and request context.
    """

    def __init__(self, name: str):
        """Initialize structured logger.

        Args:
            name: Logger name (typically module name)
        """
        self.name = name
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        msg: str,
        context: Optional[RequestContext] = None,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Internal logging method.

        Args:
            level: Log level
            msg: Log message
            context: Optional request context
            exc_info: Whether to include exception info
            **kwargs: Additional fields to include in log
        """
        # Merge context into kwargs
        if context:
            kwargs.update(context.to_dict())

        # Create log record with extra fields
        extra = {k: v for k, v in kwargs.items()}
        self._logger.log(level, msg, exc_info=exc_info, extra=extra)

    def debug(
        self,
        msg: str,
        context: Optional[RequestContext] = None,
        **kwargs: Any,
    ) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, msg, context, **kwargs)

    def info(
        self,
        msg: str,
        context: Optional[RequestContext] = None,
        **kwargs: Any,
    ) -> None:
        """Log info message."""
        self._log(logging.INFO, msg, context, **kwargs)

    def warning(
        self,
        msg: str,
        context: Optional[RequestContext] = None,
        **kwargs: Any,
    ) -> None:
        """Log warning message."""
        self._log(logging.WARNING, msg, context, **kwargs)

    def error(
        self,
        msg: str,
        context: Optional[RequestContext] = None,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Log error message."""
        self._log(logging.ERROR, msg, context, exc_info=exc_info, **kwargs)

    def critical(
        self,
        msg: str,
        context: Optional[RequestContext] = None,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, msg, context, exc_info=exc_info, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger.

    Args:
        name: Logger name (typically module name)

    Returns:
        StructuredLogger instance
    """
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]


def configure_logging(
    level: str = DEFAULT_LOG_LEVEL,
    json_format: bool = True,
    service_name: str = DEFAULT_SERVICE_NAME,
) -> None:
    """Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to use JSON format
        service_name: Service name for log identification
    """
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))

    # Set formatter
    if json_format:
        handler.setFormatter(JsonFormatter(service_name=service_name))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )

    root_logger.addHandler(handler)
