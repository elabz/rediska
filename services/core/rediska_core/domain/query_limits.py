"""Query limits and timeout configuration for Elasticsearch.

Provides safeguards to prevent runaway queries:
- Timeout limits to prevent long-running queries
- Max results limits to prevent memory issues
- Min score filtering for relevance
"""

import os
from dataclasses import dataclass
from typing import Any, Optional


# Default limits
DEFAULT_ES_TIMEOUT = 10000  # 10 seconds
DEFAULT_ES_MAX_RESULTS = 100
MAX_ES_TIMEOUT = 30000  # 30 seconds
MAX_ES_RESULTS = 1000
MIN_ES_TIMEOUT = 100  # 100ms minimum


@dataclass
class QueryLimits:
    """Configuration for query limits and timeouts.

    Attributes:
        timeout_ms: Query timeout in milliseconds
        max_results: Maximum number of results to return
        min_score: Minimum score for results (optional)
        max_timeout_ms: Maximum allowed timeout (for clamping)
        max_results_limit: Maximum allowed results (for clamping)
    """

    timeout_ms: int = DEFAULT_ES_TIMEOUT
    max_results: int = DEFAULT_ES_MAX_RESULTS
    min_score: Optional[float] = None
    max_timeout_ms: int = MAX_ES_TIMEOUT
    max_results_limit: int = MAX_ES_RESULTS

    def __post_init__(self):
        """Validate and normalize limits."""
        # Ensure timeout is within bounds
        if self.timeout_ms < MIN_ES_TIMEOUT:
            self.timeout_ms = MIN_ES_TIMEOUT
        if self.timeout_ms > self.max_timeout_ms:
            self.timeout_ms = self.max_timeout_ms

        # Ensure max_results is within bounds
        if self.max_results < 1:
            self.max_results = 1
        if self.max_results > self.max_results_limit:
            self.max_results = self.max_results_limit

    def to_dict(self) -> dict[str, Any]:
        """Convert limits to dictionary."""
        result = {
            "timeout_ms": self.timeout_ms,
            "max_results": self.max_results,
        }
        if self.min_score is not None:
            result["min_score"] = self.min_score
        return result

    def to_es_params(self) -> dict[str, Any]:
        """Convert limits to Elasticsearch query parameters.

        Returns:
            Dictionary with ES-compatible parameter names
        """
        result = {
            "timeout": f"{self.timeout_ms}ms",
            "size": self.max_results,
        }
        if self.min_score is not None:
            result["min_score"] = self.min_score
        return result

    @classmethod
    def from_env(cls) -> "QueryLimits":
        """Create QueryLimits from environment variables.

        Environment variables:
            ES_QUERY_TIMEOUT_MS: Query timeout in milliseconds
            ES_MAX_RESULTS: Maximum number of results
            ES_MIN_SCORE: Minimum score for results
        """
        timeout_ms = int(os.getenv("ES_QUERY_TIMEOUT_MS", str(DEFAULT_ES_TIMEOUT)))
        max_results = int(os.getenv("ES_MAX_RESULTS", str(DEFAULT_ES_MAX_RESULTS)))

        min_score_str = os.getenv("ES_MIN_SCORE")
        min_score = float(min_score_str) if min_score_str else None

        return cls(
            timeout_ms=timeout_ms,
            max_results=max_results,
            min_score=min_score,
        )


class QueryTimeoutError(Exception):
    """Exception raised when a query times out.

    Attributes:
        query_type: Type of query that timed out
        timeout_ms: Timeout value in milliseconds
        partial_results: Number of partial results returned (if any)
    """

    def __init__(
        self,
        query_type: str,
        timeout_ms: int,
        partial_results: Optional[int] = None,
        message: Optional[str] = None,
    ):
        self.query_type = query_type
        self.timeout_ms = timeout_ms
        self.partial_results = partial_results

        if message is None:
            message = f"{query_type} query timed out after {timeout_ms}ms"
            if partial_results is not None:
                message += f" (returned {partial_results} partial results)"

        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for API response."""
        result = {
            "error_type": "query_timeout",
            "query_type": self.query_type,
            "timeout_ms": self.timeout_ms,
            "message": str(self),
        }
        if self.partial_results is not None:
            result["partial_results"] = self.partial_results
        return result


def apply_query_limits(
    query: dict[str, Any],
    limits: QueryLimits,
) -> dict[str, Any]:
    """Apply query limits to an Elasticsearch query.

    This function adds timeout, size, and min_score parameters
    to an existing ES query dictionary.

    Args:
        query: Elasticsearch query dictionary
        limits: QueryLimits configuration

    Returns:
        Modified query dictionary with limits applied
    """
    result = query.copy()

    # Add timeout
    result["timeout"] = f"{limits.timeout_ms}ms"

    # Apply size limit
    existing_size = result.get("size")
    if existing_size is None:
        result["size"] = limits.max_results
    elif existing_size > limits.max_results:
        result["size"] = limits.max_results
    # If existing size is smaller, keep it

    # Add min_score if specified
    if limits.min_score is not None:
        result["min_score"] = limits.min_score

    return result


def create_safe_search_query(
    query_body: dict[str, Any],
    limits: Optional[QueryLimits] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a search query with safety limits applied.

    This is a convenience function for creating ES queries
    with limits already applied.

    Args:
        query_body: The query body (bool, match, etc.)
        limits: Optional QueryLimits (uses defaults if None)
        **kwargs: Additional query parameters (sort, _source, etc.)

    Returns:
        Complete query dictionary with limits applied
    """
    if limits is None:
        limits = QueryLimits.from_env()

    query = {"query": query_body}
    query.update(kwargs)

    return apply_query_limits(query, limits)
