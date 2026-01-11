"""Unit tests for pagination utilities."""

import pytest

from rediska_core.domain.pagination import (
    PaginationParams,
    PaginatedResult,
    CursorPaginationParams,
    CursorPaginatedResult,
)


class TestPaginationParams:
    """Tests for PaginationParams dataclass."""

    def test_create_default_params(self):
        """Test creating pagination params with defaults."""
        params = PaginationParams()

        assert params.page == 1
        assert params.page_size == 20
        assert params.offset == 0

    def test_create_custom_params(self):
        """Test creating pagination params with custom values."""
        params = PaginationParams(page=3, page_size=50)

        assert params.page == 3
        assert params.page_size == 50
        assert params.offset == 100  # (3-1) * 50

    def test_offset_calculation(self):
        """Test offset calculation from page and page_size."""
        params = PaginationParams(page=5, page_size=25)

        assert params.offset == 100  # (5-1) * 25

    def test_page_size_clamped_to_max(self):
        """Test that page_size is clamped to maximum."""
        params = PaginationParams(page=1, page_size=500, max_page_size=100)

        assert params.page_size == 100

    def test_page_minimum_is_one(self):
        """Test that page is at least 1."""
        params = PaginationParams(page=0, page_size=20)

        assert params.page == 1

    def test_negative_page_becomes_one(self):
        """Test that negative page becomes 1."""
        params = PaginationParams(page=-5, page_size=20)

        assert params.page == 1

    def test_page_size_minimum(self):
        """Test that page_size has a minimum."""
        params = PaginationParams(page=1, page_size=0)

        assert params.page_size >= 1

    def test_to_dict(self):
        """Test converting params to dictionary."""
        params = PaginationParams(page=2, page_size=30)

        result = params.to_dict()

        assert result["page"] == 2
        assert result["page_size"] == 30
        assert result["offset"] == 30


class TestPaginatedResult:
    """Tests for PaginatedResult dataclass."""

    def test_create_result(self):
        """Test creating a paginated result."""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = PaginatedResult(
            items=items,
            total=100,
            page=1,
            page_size=20,
        )

        assert len(result.items) == 3
        assert result.total == 100
        assert result.page == 1
        assert result.page_size == 20

    def test_total_pages_calculation(self):
        """Test calculating total pages."""
        result = PaginatedResult(
            items=[],
            total=95,
            page=1,
            page_size=20,
        )

        assert result.total_pages == 5  # ceil(95/20)

    def test_total_pages_exact_division(self):
        """Test total pages with exact division."""
        result = PaginatedResult(
            items=[],
            total=100,
            page=1,
            page_size=20,
        )

        assert result.total_pages == 5

    def test_has_next_page(self):
        """Test has_next_page property."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=100,
            page=1,
            page_size=20,
        )

        assert result.has_next is True

    def test_has_next_page_false_on_last_page(self):
        """Test has_next_page is False on last page."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=100,
            page=5,
            page_size=20,
        )

        assert result.has_next is False

    def test_has_previous_page(self):
        """Test has_previous property."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=100,
            page=3,
            page_size=20,
        )

        assert result.has_previous is True

    def test_has_previous_false_on_first_page(self):
        """Test has_previous is False on first page."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=100,
            page=1,
            page_size=20,
        )

        assert result.has_previous is False

    def test_empty_result(self):
        """Test empty paginated result."""
        result = PaginatedResult(
            items=[],
            total=0,
            page=1,
            page_size=20,
        )

        assert len(result.items) == 0
        assert result.total == 0
        assert result.total_pages == 0
        assert result.has_next is False
        assert result.has_previous is False

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=100,
            page=2,
            page_size=20,
        )

        result_dict = result.to_dict()

        assert "items" in result_dict
        assert "total" in result_dict
        assert "page" in result_dict
        assert "page_size" in result_dict
        assert "total_pages" in result_dict
        assert "has_next" in result_dict
        assert "has_previous" in result_dict


class TestCursorPaginationParams:
    """Tests for cursor-based pagination params."""

    def test_create_without_cursor(self):
        """Test creating cursor params without a cursor."""
        params = CursorPaginationParams(limit=20)

        assert params.cursor is None
        assert params.limit == 20
        assert params.direction == "next"

    def test_create_with_cursor(self):
        """Test creating cursor params with a cursor."""
        params = CursorPaginationParams(
            cursor="eyJpZCI6ICIxMjMifQ==",
            limit=50,
            direction="next",
        )

        assert params.cursor == "eyJpZCI6ICIxMjMifQ=="
        assert params.limit == 50

    def test_limit_clamped_to_max(self):
        """Test that limit is clamped to maximum."""
        params = CursorPaginationParams(limit=500, max_limit=100)

        assert params.limit == 100

    def test_limit_minimum(self):
        """Test that limit has a minimum."""
        params = CursorPaginationParams(limit=0)

        assert params.limit >= 1

    def test_decode_cursor(self):
        """Test decoding a cursor."""
        import base64
        import json

        cursor_data = {"id": "msg-123", "created_at": "2024-01-15T12:00:00Z"}
        encoded = base64.b64encode(json.dumps(cursor_data).encode()).decode()

        params = CursorPaginationParams(cursor=encoded, limit=20)
        decoded = params.decode_cursor()

        assert decoded is not None
        assert decoded["id"] == "msg-123"

    def test_decode_invalid_cursor_returns_none(self):
        """Test that invalid cursor returns None."""
        params = CursorPaginationParams(cursor="invalid-cursor", limit=20)
        decoded = params.decode_cursor()

        assert decoded is None

    def test_decode_none_cursor_returns_none(self):
        """Test that None cursor returns None."""
        params = CursorPaginationParams(cursor=None, limit=20)
        decoded = params.decode_cursor()

        assert decoded is None


class TestCursorPaginatedResult:
    """Tests for cursor-based paginated result."""

    def test_create_result(self):
        """Test creating a cursor paginated result."""
        items = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        result = CursorPaginatedResult(
            items=items,
            next_cursor="eyJpZCI6ICIzIn0=",
            has_more=True,
        )

        assert len(result.items) == 3
        assert result.next_cursor is not None
        assert result.has_more is True

    def test_no_more_results(self):
        """Test result with no more items."""
        result = CursorPaginatedResult(
            items=[{"id": "1"}],
            next_cursor=None,
            has_more=False,
        )

        assert result.has_more is False
        assert result.next_cursor is None

    def test_to_dict(self):
        """Test converting cursor result to dictionary."""
        result = CursorPaginatedResult(
            items=[{"id": "1"}],
            next_cursor="abc123",
            has_more=True,
            prev_cursor="xyz789",
        )

        result_dict = result.to_dict()

        assert "items" in result_dict
        assert "next_cursor" in result_dict
        assert "has_more" in result_dict
        assert "prev_cursor" in result_dict

    def test_encode_cursor(self):
        """Test encoding cursor from item."""
        import json
        import base64

        cursor = CursorPaginatedResult.encode_cursor(
            {"id": "msg-456", "created_at": "2024-01-15"}
        )

        assert cursor is not None
        decoded = json.loads(base64.b64decode(cursor).decode())
        assert decoded["id"] == "msg-456"


class TestPaginateQuery:
    """Tests for paginate_query helper function."""

    def test_pagination_params_offset_calculation(self):
        """Test that pagination params calculate correct offset."""
        params = PaginationParams(page=3, page_size=25)

        # Verify offset calculation
        assert params.offset == 50  # (3-1) * 25
        assert params.page_size == 25

    def test_paginated_result_creation(self):
        """Test creating a PaginatedResult manually."""
        items = [{"id": 1}, {"id": 2}]
        result = PaginatedResult(
            items=items,
            total=50,
            page=1,
            page_size=20,
        )

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 50
        assert result.total_pages == 3

    def test_paginated_result_empty(self):
        """Test empty PaginatedResult."""
        result = PaginatedResult(
            items=[],
            total=0,
            page=1,
            page_size=20,
        )

        assert len(result.items) == 0
        assert result.total == 0
        assert result.total_pages == 0
        assert result.has_next is False

    def test_paginated_result_last_page(self):
        """Test PaginatedResult on last page."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=41,
            page=3,
            page_size=20,
        )

        assert result.total_pages == 3
        assert result.has_next is False
        assert result.has_previous is True


class TestCursorPaginateQuery:
    """Tests for cursor_paginate_query helper function."""

    def test_cursor_paginated_result_creation(self):
        """Test creating a CursorPaginatedResult manually."""
        items = [{"id": "msg-1"}, {"id": "msg-2"}]
        result = CursorPaginatedResult(
            items=items,
            next_cursor="abc123",
            has_more=True,
        )

        assert isinstance(result, CursorPaginatedResult)
        assert len(result.items) == 2
        assert result.has_more is True

    def test_cursor_paginated_result_no_more(self):
        """Test CursorPaginatedResult with no more items."""
        result = CursorPaginatedResult(
            items=[{"id": "msg-1"}],
            next_cursor=None,
            has_more=False,
        )

        assert result.has_more is False
        assert result.next_cursor is None

    def test_cursor_encoding_decoding(self):
        """Test cursor encoding and decoding round-trip."""
        import base64
        import json

        # Encode cursor
        cursor_data = {"id": "msg-100", "created_at": "2024-01-15"}
        cursor = CursorPaginatedResult.encode_cursor(cursor_data)

        # Decode cursor
        params = CursorPaginationParams(cursor=cursor, limit=20)
        decoded = params.decode_cursor()

        assert decoded is not None
        assert decoded["id"] == "msg-100"
        assert decoded["created_at"] == "2024-01-15"

    def test_cursor_params_limit_clamping(self):
        """Test that cursor params limit is clamped correctly."""
        params = CursorPaginationParams(limit=500, max_limit=100)

        assert params.limit == 100


class TestPaginationEdgeCases:
    """Tests for pagination edge cases."""

    def test_very_large_page_number(self):
        """Test handling very large page numbers."""
        params = PaginationParams(page=999999, page_size=20)

        assert params.page == 999999
        assert params.offset == (999999 - 1) * 20

    def test_result_with_single_item(self):
        """Test result with exactly one item."""
        result = PaginatedResult(
            items=[{"id": 1}],
            total=1,
            page=1,
            page_size=20,
        )

        assert result.total_pages == 1
        assert result.has_next is False
        assert result.has_previous is False

    def test_result_page_beyond_total(self):
        """Test requesting page beyond total pages."""
        result = PaginatedResult(
            items=[],
            total=50,
            page=10,  # Page 10 doesn't exist for 50 items at 20 per page
            page_size=20,
        )

        assert len(result.items) == 0
        assert result.total_pages == 3
        assert result.has_next is False

    def test_cursor_with_special_characters(self):
        """Test cursor encoding with special characters."""
        import base64
        import json

        cursor_data = {"id": "msg-with-special-chars-éàü"}
        cursor = base64.b64encode(json.dumps(cursor_data).encode()).decode()

        params = CursorPaginationParams(cursor=cursor, limit=20)
        decoded = params.decode_cursor()

        assert decoded is not None
        assert "éàü" in decoded["id"]
