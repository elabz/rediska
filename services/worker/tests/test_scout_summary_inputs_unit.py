"""Unit tests for the summary input selector used by the scout pipeline."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from rediska_worker.tasks.scout import (
    MAX_PROFILE_COMMENTS,
    MAX_PROFILE_POSTS,
    _select_summary_items,
)


def item(kind, text, days_ago=None, id=0):
    return SimpleNamespace(
        id=id,
        item_type=kind,
        text_content=text,
        item_created_at=(datetime(2026, 9, 16) - timedelta(days=days_ago)) if days_ago is not None else None,
    )


class TestSelectSummaryItems:
    def test_uses_discovery_post_when_fresh_history_is_empty(self):
        # Only the discovery post (no date, stored by the scout task) exists
        posts, comments = _select_summary_items([item("post", "Title\n\nListing body", id=1)])
        assert [p.text_content for p in posts] == ["Title\n\nListing body"]
        assert comments == []

    def test_newest_first_unknown_dates_last_and_dedup(self):
        items = [
            item("post", "same ad", days_ago=3, id=1),
            item("post", "SAME   ad", days_ago=1, id=2),  # duplicate text, different spacing/case
            item("post", "older unique", days_ago=10, id=3),
            item("post", "undated", id=4),
            item("comment", "a comment", days_ago=2, id=5),
            item("comment", "", days_ago=1, id=6),  # empty, dropped
        ]
        posts, comments = _select_summary_items(items)
        assert [p.id for p in posts] == [2, 3, 4]
        assert [c.id for c in comments] == [5]

    def test_caps(self):
        items = [item("post", f"p{i}", days_ago=i, id=i) for i in range(MAX_PROFILE_POSTS + 5)]
        items += [item("comment", f"c{i}", days_ago=i, id=1000 + i) for i in range(MAX_PROFILE_COMMENTS + 5)]
        posts, comments = _select_summary_items(items)
        assert len(posts) == MAX_PROFILE_POSTS
        assert len(comments) == MAX_PROFILE_COMMENTS
        assert posts[0].text_content == "p0"
