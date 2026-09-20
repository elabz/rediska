"""Embedding text preparation: one rule, a hard input budget, chunk means.

Synthetic text only.
"""

import pytest

from rediska_core.domain.services.embedding_text import (
    DEFAULT_MAX_CHARS,
    DOCUMENT_PREFIX,
    MAX_CHUNKS,
    PREP_VERSION,
    QUERY_PREFIX,
    as_document,
    as_query,
    chunk_text,
    collapse,
    mean_vector,
    prepare_embedding_text,
    text_hash,
)


class TestPrepare:
    def test_title_blank_line_body(self):
        assert prepare_embedding_text("A title", "Line one\nline two") == (
            "A title\n\nLine one\nline two"
        )

    def test_missing_parts(self):
        assert prepare_embedding_text(None, "body") == "body"
        assert prepare_embedding_text("title", None) == "title"
        assert prepare_embedding_text(None, None) == ""
        assert prepare_embedding_text("  ", "  ") == ""

    def test_whitespace_is_collapsed_but_paragraphs_survive(self):
        prepared = prepare_embedding_text("T   x", "a  b\n\n\n\nc   d")
        assert prepared == "T x\n\na b\n\nc d"
        assert collapse("  \t lots   of\r\n space ") == "lots of\n space"

    def test_listing_details_block_is_kept(self):
        body = "[Listing details from weheartbdsm.com]\nAge: 30\n\nAbout me"
        assert "Listing details" in prepare_embedding_text(None, body)


class TestChunking:
    def test_short_text_is_one_chunk(self):
        chunks = chunk_text("short enough")
        assert chunks == ["short enough"]

    def test_empty_text_has_no_chunks(self):
        assert chunk_text("") == [] and chunk_text("   ") == []

    def test_long_text_splits_on_paragraphs_within_budget(self):
        para = " ".join(["word"] * 100)  # ~500 chars
        chunks = chunk_text("\n\n".join([para] * 6))
        assert 1 < len(chunks) <= MAX_CHUNKS
        assert all(len(c) <= DEFAULT_MAX_CHARS for c in chunks)
        assert all("\n\n\n" not in c for c in chunks)

    def test_long_text_without_paragraph_breaks_still_fits(self):
        chunks = chunk_text(" ".join(["word"] * 2000))
        assert chunks and all(len(c) <= DEFAULT_MAX_CHARS for c in chunks)
        assert len(chunks) == MAX_CHUNKS  # capped

    def test_single_word_longer_than_budget_is_cut(self):
        chunks = chunk_text("x" * (DEFAULT_MAX_CHARS * 2))
        assert all(len(c) <= DEFAULT_MAX_CHARS for c in chunks)

    def test_nothing_over_budget_is_ever_returned(self):
        text = "\n\n".join(" ".join(["w"] * 400) for _ in range(10))
        assert all(len(c) <= DEFAULT_MAX_CHARS for c in chunk_text(text))


class TestPrefixesAndHash:
    def test_prefixes(self):
        assert as_document("x") == f"{DOCUMENT_PREFIX}x"
        assert as_query("x") == f"{QUERY_PREFIX}x"
        assert DOCUMENT_PREFIX != QUERY_PREFIX

    def test_hash_is_stable_and_content_sensitive(self):
        assert text_hash("same") == text_hash("same")
        assert text_hash("same") != text_hash("other")

    def test_hash_covers_the_prep_version(self):
        import rediska_core.domain.services.embedding_text as mod

        before = text_hash("same")
        original = mod.PREP_VERSION
        try:
            mod.PREP_VERSION = "v2-test"
            assert text_hash("same") != before
        finally:
            mod.PREP_VERSION = original
        assert PREP_VERSION == original


class TestMeanVector:
    def test_single_vector_is_normalised(self):
        out = mean_vector([[3.0, 4.0]])
        assert out == pytest.approx([0.6, 0.8])

    def test_mean_is_normalised(self):
        out = mean_vector([[1.0, 0.0], [0.0, 1.0]])
        assert out == pytest.approx([2 ** -0.5, 2 ** -0.5])
        assert sum(v * v for v in out) == pytest.approx(1.0)

    def test_no_vectors(self):
        assert mean_vector([]) is None
        assert mean_vector([[]]) is None

    def test_mismatched_dimensions_are_rejected(self):
        with pytest.raises(ValueError):
            mean_vector([[1.0, 0.0], [1.0]])

    def test_zero_vector_is_left_alone(self):
        assert mean_vector([[0.0, 0.0]]) == [0.0, 0.0]
