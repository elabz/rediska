"""Pagination utilities for API endpoints.

Provides both offset-based and cursor-based pagination strategies:
- Offset-based: Simple page/page_size for admin views and smaller datasets
- Cursor-based: Efficient for large datasets and real-time data (inbox, messages)
"""

import base64
import json
import math
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_CURSOR_LIMIT = 50
MAX_CURSOR_LIMIT = 100


@dataclass
class PaginationParams:
    """Parameters for offset-based pagination.

    Attributes:
        page: Current page number (1-indexed)
        page_size: Number of items per page
        max_page_size: Maximum allowed page size
    """

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    max_page_size: int = MAX_PAGE_SIZE

    def __post_init__(self):
        """Validate and normalize pagination parameters."""
        # Ensure page is at least 1
        if self.page < 1:
            self.page = 1

        # Ensure page_size is at least 1
        if self.page_size < 1:
            self.page_size = 1

        # Clamp page_size to maximum
        if self.page_size > self.max_page_size:
            self.page_size = self.max_page_size

    @property
    def offset(self) -> int:
        """Calculate offset from page and page_size."""
        return (self.page - 1) * self.page_size

    def to_dict(self) -> dict[str, Any]:
        """Convert parameters to dictionary."""
        return {
            "page": self.page,
            "page_size": self.page_size,
            "offset": self.offset,
        }

    @classmethod
    def from_query_params(
        cls,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        max_page_size: int = MAX_PAGE_SIZE,
    ) -> "PaginationParams":
        """Create PaginationParams from query parameters."""
        return cls(
            page=page or 1,
            page_size=page_size or DEFAULT_PAGE_SIZE,
            max_page_size=max_page_size,
        )


@dataclass
class PaginatedResult(Generic[T]):
    """Result container for offset-based pagination.

    Attributes:
        items: List of items for current page
        total: Total number of items across all pages
        page: Current page number
        page_size: Number of items per page
    """

    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.total == 0:
            return 0
        return math.ceil(self.total / self.page_size)

    @property
    def has_next(self) -> bool:
        """Check if there is a next page."""
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        """Check if there is a previous page."""
        return self.page > 1

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for API response."""
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
        }


@dataclass
class CursorPaginationParams:
    """Parameters for cursor-based pagination.

    Cursor-based pagination is more efficient for large datasets
    and handles real-time data changes gracefully.

    Attributes:
        cursor: Opaque cursor string (base64-encoded JSON)
        limit: Maximum number of items to return
        direction: Pagination direction ("next" or "prev")
        max_limit: Maximum allowed limit
    """

    limit: int = DEFAULT_CURSOR_LIMIT
    cursor: Optional[str] = None
    direction: str = "next"
    max_limit: int = MAX_CURSOR_LIMIT

    def __post_init__(self):
        """Validate and normalize parameters."""
        # Ensure limit is at least 1
        if self.limit < 1:
            self.limit = 1

        # Clamp limit to maximum
        if self.limit > self.max_limit:
            self.limit = self.max_limit

        # Validate direction
        if self.direction not in ("next", "prev"):
            self.direction = "next"

    def decode_cursor(self) -> Optional[dict[str, Any]]:
        """Decode cursor string to dictionary.

        Returns:
            Decoded cursor data, or None if cursor is invalid
        """
        if not self.cursor:
            return None

        try:
            decoded = base64.b64decode(self.cursor.encode()).decode()
            return json.loads(decoded)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def to_dict(self) -> dict[str, Any]:
        """Convert parameters to dictionary."""
        return {
            "cursor": self.cursor,
            "limit": self.limit,
            "direction": self.direction,
        }

    @classmethod
    def from_query_params(
        cls,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        direction: str = "next",
        max_limit: int = MAX_CURSOR_LIMIT,
    ) -> "CursorPaginationParams":
        """Create CursorPaginationParams from query parameters."""
        return cls(
            cursor=cursor,
            limit=limit or DEFAULT_CURSOR_LIMIT,
            direction=direction,
            max_limit=max_limit,
        )


@dataclass
class CursorPaginatedResult(Generic[T]):
    """Result container for cursor-based pagination.

    Attributes:
        items: List of items for current page
        next_cursor: Cursor for next page (None if no more items)
        has_more: Whether there are more items
        prev_cursor: Cursor for previous page (optional)
    """

    items: list[T]
    next_cursor: Optional[str] = None
    has_more: bool = False
    prev_cursor: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for API response."""
        return {
            "items": self.items,
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "prev_cursor": self.prev_cursor,
        }

    @staticmethod
    def encode_cursor(data: dict[str, Any]) -> str:
        """Encode cursor data to string.

        Args:
            data: Dictionary with cursor fields

        Returns:
            Base64-encoded JSON string
        """
        json_str = json.dumps(data)
        return base64.b64encode(json_str.encode()).decode()


async def paginate_query(
    session: AsyncSession,
    query: Select,
    params: PaginationParams,
) -> PaginatedResult:
    """Apply offset-based pagination to a SQLAlchemy query.

    Args:
        session: Database session
        query: SQLAlchemy select query
        params: Pagination parameters

    Returns:
        PaginatedResult with items and metadata
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination
    paginated_query = query.offset(params.offset).limit(params.page_size)
    result = await session.execute(paginated_query)
    items = list(result.scalars().all())

    return PaginatedResult(
        items=items,
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


async def cursor_paginate_query(
    session: AsyncSession,
    query: Select,
    params: CursorPaginationParams,
    cursor_field: str = "id",
    order_desc: bool = True,
) -> CursorPaginatedResult:
    """Apply cursor-based pagination to a SQLAlchemy query.

    Args:
        session: Database session
        query: SQLAlchemy select query
        params: Cursor pagination parameters
        cursor_field: Field to use for cursor comparison
        order_desc: Whether to order descending (newest first)

    Returns:
        CursorPaginatedResult with items and cursors
    """
    # Decode cursor if present
    cursor_data = params.decode_cursor()

    # Apply cursor filter if present
    if cursor_data and cursor_field in cursor_data:
        cursor_value = cursor_data[cursor_field]
        # Note: The caller should apply the actual filter based on cursor_value
        # This is a simplified implementation
        query = query.where(query.column_descriptions[0]["entity"].id < cursor_value)

    # Fetch limit + 1 to check if there are more
    fetch_query = query.limit(params.limit + 1)
    result = await session.execute(fetch_query)
    items = list(result.scalars().all())

    # Check if there are more items
    has_more = len(items) > params.limit
    if has_more:
        items = items[:params.limit]

    # Generate next cursor from last item
    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        cursor_value = getattr(last_item, cursor_field, None)
        if cursor_value is not None:
            next_cursor = CursorPaginatedResult.encode_cursor({cursor_field: str(cursor_value)})

    return CursorPaginatedResult(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


def create_pagination_response(
    result: PaginatedResult | CursorPaginatedResult,
    item_serializer: Optional[callable] = None,
) -> dict[str, Any]:
    """Create API response from pagination result.

    Args:
        result: Pagination result (offset or cursor based)
        item_serializer: Optional function to serialize items

    Returns:
        Dictionary suitable for JSON response
    """
    response = result.to_dict()

    if item_serializer:
        response["items"] = [item_serializer(item) for item in response["items"]]

    return response
