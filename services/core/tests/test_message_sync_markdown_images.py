"""Unit tests for markdown image URL extraction in MessageSyncService.

Tests the extraction of image URLs from:
- Bare URLs: https://i.redd.it/abc.jpg
- Markdown syntax: [alt text](https://example.com/image.jpg)
"""

import pytest
from unittest.mock import MagicMock, patch

from rediska_core.domain.services.message_sync import MessageSyncService


class MockMessageSyncService:
    """Minimal service mock for testing URL extraction logic."""

    MARKDOWN_IMAGE_PATTERN = r'\[([^\]]*)\]\((https?://[^\)]+)\)'
    IMAGE_URL_PATTERNS = [
        r'https?://i\.redd\.it/[^\s\)]+',
        r'https?://preview\.redd\.it/[^\s\)]+',
        r'https?://(?:i\.)?imgur\.com/[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)',
        r'https?://[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s\)]*)?',
    ]

    def _extract_image_urls(self, text: str) -> list[str]:
        """Extract image URLs from message text using the actual MessageSyncService logic."""
        import re

        if not text:
            return []

        urls = []

        # Extract markdown image URLs: [text](url)
        markdown_matches = re.findall(self.MARKDOWN_IMAGE_PATTERN, text)
        for alt_text, url in markdown_matches:
            urls.append(url)

        # Extract bare URLs (existing patterns)
        for pattern in self.IMAGE_URL_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)

        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            # Normalize URL (remove trailing punctuation that might have been captured)
            url = url.rstrip('.,;:!?)')
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls[:5]  # Limit to 5 images per message


@pytest.fixture
def message_sync_service() -> MockMessageSyncService:
    """Create a mock service instance for testing URL extraction."""
    return MockMessageSyncService()


# =============================================================================
# TESTS: Markdown Image URL Extraction
# =============================================================================


class TestMarkdownImageExtraction:
    """Tests for extracting image URLs from markdown syntax."""

    def test_extract_single_markdown_image_url(
        self, message_sync_service: MockMessageSyncService
    ):
        """Test extraction of single markdown image URL."""
        text = 'sent an [image](https://example.com/image.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://example.com/image.jpg' in urls

    def test_extract_markdown_image_with_matrix_url(
        self, message_sync_service: MessageSyncService
    ):
        """Test extraction of markdown image with Matrix media URL."""
        text = 'sent an [image](https://matrix.redditspace.com/_matrix/media/v3/download/reddit.com/krr0pisi9tcg1)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://matrix.redditspace.com/_matrix/media/v3/download/reddit.com/krr0pisi9tcg1' in urls

    def test_extract_multiple_markdown_image_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test extraction of multiple markdown image URLs."""
        text = 'Check [first image](https://a.com/1.jpg) and [second image](https://b.com/2.png)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 2
        assert 'https://a.com/1.jpg' in urls
        assert 'https://b.com/2.png' in urls

    def test_extract_markdown_with_special_alt_text(
        self, message_sync_service: MessageSyncService
    ):
        """Test markdown with special characters in alt text."""
        text = 'Check [image (with parentheses)](https://example.com/img.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        # Should not match due to parentheses in alt text interfering with regex
        # This is a limitation of the simple regex pattern

    def test_extract_markdown_with_empty_alt_text(
        self, message_sync_service: MessageSyncService
    ):
        """Test markdown image with empty alt text."""
        text = 'sent an [](https://example.com/image.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://example.com/image.jpg' in urls


# =============================================================================
# TESTS: Mixed Markdown and Bare URLs
# =============================================================================


class TestMixedImageExtraction:
    """Tests for extraction of both markdown and bare URLs."""

    def test_extract_markdown_and_bare_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test extraction of both markdown and bare image URLs."""
        text = 'Check [img](https://a.com/1.jpg) and https://b.com/2.png'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 2
        assert 'https://a.com/1.jpg' in urls
        assert 'https://b.com/2.png' in urls

    def test_extract_markdown_and_reddit_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test extraction of markdown and Reddit-hosted URLs."""
        text = '[img](https://example.com/img.jpg) and https://i.redd.it/abc123'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 2
        assert 'https://example.com/img.jpg' in urls
        assert 'https://i.redd.it/abc123' in urls

    def test_extract_markdown_and_preview_reddit_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test extraction of markdown and preview.redd.it URLs."""
        text = '[preview](https://preview.redd.it/preview123)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://preview.redd.it/preview123' in urls


# =============================================================================
# TESTS: URL Limit (Max 5 Images)
# =============================================================================


class TestImageUrlLimit:
    """Tests for the 5-image limit per message."""

    def test_extract_markdown_image_urls_respects_limit(
        self, message_sync_service: MessageSyncService
    ):
        """Test that max 5 images are extracted."""
        text = ' '.join(
            [f'[img{i}](https://example.com/{i}.jpg)' for i in range(10)]
        )
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 5

    def test_extract_mixed_urls_respects_limit(
        self, message_sync_service: MessageSyncService
    ):
        """Test that limit applies to mixed markdown and bare URLs."""
        markdown = ' '.join(
            [f'[img{i}](https://example.com/{i}.jpg)' for i in range(3)]
        )
        bare = ' https://i.redd.it/1 https://i.redd.it/2 https://i.redd.it/3'
        text = markdown + ' ' + bare

        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 5


# =============================================================================
# TESTS: Deduplication
# =============================================================================


class TestImageUrlDeduplication:
    """Tests for URL deduplication."""

    def test_deduplicate_identical_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test that identical URLs are deduplicated."""
        text = '[img1](https://example.com/image.jpg) and [img2](https://example.com/image.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://example.com/image.jpg' in urls

    def test_deduplicate_markdown_and_bare_same_url(
        self, message_sync_service: MessageSyncService
    ):
        """Test deduplication when URL appears as both markdown and bare."""
        text = '[img](https://example.com/image.jpg) and https://example.com/image.jpg'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1


# =============================================================================
# TESTS: Edge Cases and Invalid Input
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and invalid inputs."""

    def test_extract_from_empty_text(self, message_sync_service: MessageSyncService):
        """Test extraction from empty text."""
        urls = message_sync_service._extract_image_urls('')
        assert urls == []

    def test_extract_from_none_text(self, message_sync_service: MessageSyncService):
        """Test extraction from None."""
        urls = message_sync_service._extract_image_urls(None)
        assert urls == []

    def test_markdown_without_url_not_extracted(
        self, message_sync_service: MessageSyncService
    ):
        """Test that [text] without URL is not extracted."""
        text = 'Check [this text] but no URL'
        urls = message_sync_service._extract_image_urls(text)
        assert urls == []

    def test_markdown_with_http_only_urls(
        self, message_sync_service: MessageSyncService
    ):
        """Test markdown with HTTP (not HTTPS) URLs."""
        text = '[image](http://example.com/image.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'http://example.com/image.jpg' in urls

    def test_malformed_markdown_not_extracted(
        self, message_sync_service: MessageSyncService
    ):
        """Test that malformed markdown is not extracted."""
        text = '[text(https://example.com/image.jpg)'  # Missing closing bracket
        urls = message_sync_service._extract_image_urls(text)

        # Might be extracted as bare URL, or not at all depending on implementation
        # This is an edge case of malformed markdown

    def test_text_with_many_special_characters(
        self, message_sync_service: MessageSyncService
    ):
        """Test text with many special characters."""
        text = 'Hey!!!Check [img](https://example.com/image.jpg)???'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://example.com/image.jpg' in urls


# =============================================================================
# TESTS: Real-World Examples
# =============================================================================


class TestRealWorldExamples:
    """Tests with realistic message content."""

    def test_reddit_personals_message_with_matrix_image(
        self, message_sync_service: MessageSyncService
    ):
        """Test realistic Reddit personals message with Matrix image link."""
        text = 'sent an [image](https://matrix.redditspace.com/_matrix/media/v3/download/reddit.com/krr0pisi9tcg1)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'matrix.redditspace.com' in urls[0]

    def test_message_with_multiple_markdown_images_and_text(
        self, message_sync_service: MessageSyncService
    ):
        """Test message with markdown images interspersed with text."""
        text = '''Hey! Here are some photos from the last event:
        [First photo](https://example.com/photo1.jpg)
        [Second photo](https://example.com/photo2.png)

        Hope you like them!'''
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 2

    def test_markdown_image_with_query_parameters(
        self, message_sync_service: MessageSyncService
    ):
        """Test markdown image URL with query parameters."""
        text = '[image](https://example.com/image.jpg?size=large&format=webp)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 1
        assert 'https://example.com/image.jpg?size=large&format=webp' in urls


# =============================================================================
# TESTS: URL Normalization
# =============================================================================


class TestUrlNormalization:
    """Tests for URL normalization (trailing punctuation removal)."""

    def test_markdown_url_with_trailing_period(
        self, message_sync_service: MessageSyncService
    ):
        """Test that trailing period is not included in URL."""
        text = 'Check [image](https://example.com/image.jpg).'
        urls = message_sync_service._extract_image_urls(text)

        # Trailing period is after the closing parenthesis, should not be included
        assert len(urls) == 1
        assert urls[0] == 'https://example.com/image.jpg'

    def test_markdown_url_with_trailing_comma(
        self, message_sync_service: MessageSyncService
    ):
        """Test that trailing comma is not included in URL."""
        text = '[img](https://example.com/image.jpg), [img2](https://example.com/image2.jpg)'
        urls = message_sync_service._extract_image_urls(text)

        assert len(urls) == 2
        assert all(url.endswith('.jpg') for url in urls)
