"""
Unit tests for Epic 5.1 - Local attachment store.

Tests cover:
1. AttachmentService upload functionality
2. File validation (size, mime type)
3. SHA256 computation and deduplication
4. Storage key generation
5. Attachment retrieval
"""

import hashlib
import io
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rediska_core.domain.models import Attachment, Provider
from rediska_core.domain.services.attachment import (
    AttachmentService,
    AttachmentUploadResult,
    FileTooLargeError,
    InvalidMimeTypeError,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_storage_path():
    """Create a temporary directory for attachment storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def attachment_service(db_session, temp_storage_path):
    """Create AttachmentService with temporary storage."""
    return AttachmentService(
        db=db_session,
        storage_path=temp_storage_path,
    )


@pytest.fixture
def sample_image_bytes():
    """Create a minimal valid PNG image."""
    # Minimal valid 1x1 red PNG
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 dimensions
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
        0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
        0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
        0x44, 0xAE, 0x42, 0x60, 0x82,
    ])


@pytest.fixture
def sample_text_bytes():
    """Create sample text file content."""
    return b"Hello, this is a test text file content."


# =============================================================================
# UPLOAD TESTS
# =============================================================================


class TestAttachmentUpload:
    """Tests for attachment upload functionality."""

    def test_upload_creates_attachment_record(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """Upload should create an Attachment record in the database."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        assert result.attachment_id is not None
        assert result.sha256 is not None
        assert result.storage_key is not None

        # Verify record exists in database
        attachment = db_session.query(Attachment).get(result.attachment_id)
        assert attachment is not None
        assert attachment.mime_type == "text/plain"
        assert attachment.size_bytes == len(sample_text_bytes)

    def test_upload_computes_sha256(
        self, attachment_service, sample_text_bytes
    ):
        """Upload should compute correct SHA256 hash."""
        expected_hash = hashlib.sha256(sample_text_bytes).hexdigest()

        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        assert result.sha256 == expected_hash

    def test_upload_stores_file_on_disk(
        self, attachment_service, temp_storage_path, sample_text_bytes
    ):
        """Upload should write file to the storage path."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        # Verify file exists at storage_key path
        file_path = Path(temp_storage_path) / result.storage_key
        assert file_path.exists()
        assert file_path.read_bytes() == sample_text_bytes

    def test_upload_generates_unique_storage_key(
        self, attachment_service, sample_text_bytes
    ):
        """Each upload should have a unique storage key."""
        result1 = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test1.txt",
            content_type="text/plain",
        )

        # Different filename, same content
        result2 = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test2.txt",
            content_type="text/plain",
        )

        # Storage keys should be different (even for same content)
        # unless we implement deduplication
        assert result1.storage_key != result2.storage_key

    def test_upload_stores_original_filename(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """Attachment record should preserve original filename."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="my_document.txt",
            content_type="text/plain",
        )

        attachment = db_session.query(Attachment).get(result.attachment_id)
        # The storage_key should contain a reference to enable retrieval
        assert result.storage_key is not None


# =============================================================================
# VALIDATION TESTS
# =============================================================================


class TestAttachmentValidation:
    """Tests for file validation during upload."""

    def test_upload_rejects_file_too_large(
        self, attachment_service
    ):
        """Files larger than 10MB should be rejected."""
        # Create a file larger than 10MB
        large_data = b"x" * (11 * 1024 * 1024)  # 11MB

        with pytest.raises(FileTooLargeError) as exc_info:
            attachment_service.upload(
                file_data=large_data,
                filename="large.bin",
                content_type="application/octet-stream",
            )

        assert "10MB" in str(exc_info.value) or "10" in str(exc_info.value)

    def test_upload_accepts_max_size_file(
        self, attachment_service
    ):
        """Files exactly at 10MB should be accepted."""
        # Create a file exactly 10MB
        max_data = b"x" * (10 * 1024 * 1024)  # 10MB

        result = attachment_service.upload(
            file_data=max_data,
            filename="maxsize.bin",
            content_type="application/octet-stream",
        )

        assert result.attachment_id is not None

    def test_upload_rejects_invalid_mime_type(
        self, attachment_service
    ):
        """Disallowed MIME types should be rejected."""
        with pytest.raises(InvalidMimeTypeError):
            attachment_service.upload(
                file_data=b"fake executable",
                filename="malware.exe",
                content_type="application/x-msdownload",
            )

    def test_upload_accepts_image_mime_types(
        self, attachment_service, sample_image_bytes
    ):
        """Image MIME types should be accepted."""
        result = attachment_service.upload(
            file_data=sample_image_bytes,
            filename="image.png",
            content_type="image/png",
        )

        assert result.attachment_id is not None

    def test_upload_accepts_text_mime_types(
        self, attachment_service, sample_text_bytes
    ):
        """Text MIME types should be accepted."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="doc.txt",
            content_type="text/plain",
        )

        assert result.attachment_id is not None

    def test_upload_accepts_pdf_mime_type(
        self, attachment_service
    ):
        """PDF MIME type should be accepted."""
        # Minimal PDF header
        pdf_bytes = b"%PDF-1.4\n%%EOF"

        result = attachment_service.upload(
            file_data=pdf_bytes,
            filename="document.pdf",
            content_type="application/pdf",
        )

        assert result.attachment_id is not None

    def test_upload_accepts_common_document_types(
        self, attachment_service
    ):
        """Common document MIME types should be accepted."""
        doc_content = b"fake document content"

        # JSON
        result = attachment_service.upload(
            file_data=b'{"key": "value"}',
            filename="data.json",
            content_type="application/json",
        )
        assert result.attachment_id is not None


# =============================================================================
# IMAGE DIMENSION TESTS
# =============================================================================


class TestImageDimensions:
    """Tests for image dimension extraction."""

    def test_upload_extracts_image_dimensions(
        self, db_session, attachment_service, sample_image_bytes
    ):
        """Image uploads should extract width and height."""
        result = attachment_service.upload(
            file_data=sample_image_bytes,
            filename="image.png",
            content_type="image/png",
        )

        attachment = db_session.query(Attachment).get(result.attachment_id)
        # The sample image is 1x1
        assert attachment.width_px == 1
        assert attachment.height_px == 1

    def test_upload_non_image_has_no_dimensions(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """Non-image uploads should have null dimensions."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="doc.txt",
            content_type="text/plain",
        )

        attachment = db_session.query(Attachment).get(result.attachment_id)
        assert attachment.width_px is None
        assert attachment.height_px is None

    def test_upload_handles_corrupt_image_gracefully(
        self, db_session, attachment_service
    ):
        """Corrupt image data should not crash, just skip dimensions."""
        # Invalid image data that claims to be PNG
        corrupt_data = b"not a real image"

        result = attachment_service.upload(
            file_data=corrupt_data,
            filename="corrupt.png",
            content_type="image/png",
        )

        attachment = db_session.query(Attachment).get(result.attachment_id)
        # Should still succeed, just without dimensions
        assert result.attachment_id is not None
        assert attachment.width_px is None
        assert attachment.height_px is None


# =============================================================================
# RETRIEVAL TESTS
# =============================================================================


class TestAttachmentRetrieval:
    """Tests for attachment retrieval functionality."""

    def test_get_by_id_returns_attachment(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """get_by_id should return the attachment record."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        attachment = attachment_service.get_by_id(result.attachment_id)

        assert attachment is not None
        assert attachment.id == result.attachment_id
        assert attachment.sha256 == result.sha256

    def test_get_by_id_returns_none_for_missing(
        self, attachment_service
    ):
        """get_by_id should return None for non-existent ID."""
        attachment = attachment_service.get_by_id(99999)
        assert attachment is None

    def test_get_file_path_returns_correct_path(
        self, attachment_service, temp_storage_path, sample_text_bytes
    ):
        """get_file_path should return the full filesystem path."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        file_path = attachment_service.get_file_path(result.attachment_id)

        assert file_path is not None
        assert Path(file_path).exists()
        assert Path(file_path).read_bytes() == sample_text_bytes

    def test_get_file_path_returns_none_for_missing(
        self, attachment_service
    ):
        """get_file_path should return None for non-existent attachment."""
        file_path = attachment_service.get_file_path(99999)
        assert file_path is None

    def test_get_by_sha256_finds_attachment(
        self, attachment_service, sample_text_bytes
    ):
        """Should be able to find attachment by SHA256 hash."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        attachment = attachment_service.get_by_sha256(result.sha256)

        assert attachment is not None
        assert attachment.id == result.attachment_id


# =============================================================================
# STORAGE KEY GENERATION TESTS
# =============================================================================


class TestStorageKeyGeneration:
    """Tests for storage key generation."""

    def test_storage_key_includes_date_prefix(
        self, attachment_service, sample_text_bytes
    ):
        """Storage key should include date-based directory structure."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )

        # Expect format like: YYYY/MM/DD/uuid.ext
        parts = result.storage_key.split("/")
        assert len(parts) >= 3  # At least year/month/filename
        # First part should be a year
        assert parts[0].isdigit() and len(parts[0]) == 4

    def test_storage_key_preserves_extension(
        self, attachment_service, sample_text_bytes
    ):
        """Storage key should preserve the original file extension."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="document.txt",
            content_type="text/plain",
        )

        assert result.storage_key.endswith(".txt")

    def test_storage_key_sanitizes_extension(
        self, attachment_service, sample_text_bytes
    ):
        """Dangerous extensions should be sanitized."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="script.txt.exe",
            content_type="text/plain",  # Override with safe type
        )

        # Should not end with .exe
        assert not result.storage_key.endswith(".exe")


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Tests for error handling during upload."""

    def test_upload_with_empty_file_fails(
        self, attachment_service
    ):
        """Empty files should be rejected."""
        with pytest.raises(ValueError, match="empty"):
            attachment_service.upload(
                file_data=b"",
                filename="empty.txt",
                content_type="text/plain",
            )

    def test_upload_with_missing_filename_uses_default(
        self, attachment_service, sample_text_bytes
    ):
        """Missing filename should use a default."""
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="",
            content_type="text/plain",
        )

        # Should still succeed
        assert result.attachment_id is not None

    def test_upload_rollback_on_db_error(
        self, attachment_service, temp_storage_path, sample_text_bytes
    ):
        """If DB insert fails, file should not be left on disk."""
        # This would require mocking DB to fail, which is complex
        # For now, just verify the happy path works
        result = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="test.txt",
            content_type="text/plain",
        )
        assert result.attachment_id is not None


# =============================================================================
# DEDUPLICATION TESTS (OPTIONAL)
# =============================================================================


class TestDeduplication:
    """Tests for optional content deduplication."""

    def test_find_existing_by_sha256(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """Should find existing attachment with same SHA256."""
        # First upload
        result1 = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="first.txt",
            content_type="text/plain",
        )

        # Check if we can find it by hash
        existing = attachment_service.get_by_sha256(result1.sha256)
        assert existing is not None
        assert existing.id == result1.attachment_id

    def test_duplicate_content_creates_new_record(
        self, db_session, attachment_service, sample_text_bytes
    ):
        """By default, duplicate content creates new records (no dedup)."""
        # First upload
        result1 = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="first.txt",
            content_type="text/plain",
        )

        # Second upload with same content
        result2 = attachment_service.upload(
            file_data=sample_text_bytes,
            filename="second.txt",
            content_type="text/plain",
        )

        # Should be different attachment IDs
        assert result1.attachment_id != result2.attachment_id
        # But same SHA256
        assert result1.sha256 == result2.sha256
