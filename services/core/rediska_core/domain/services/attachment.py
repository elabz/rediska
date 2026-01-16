"""Attachment service for local file storage.

This service handles:
1. File uploads with validation (size, MIME type)
2. SHA256 hash computation
3. Image dimension extraction
4. Storage key generation with date-based directory structure
5. File retrieval by ID or SHA256

Usage:
    service = AttachmentService(db=session, storage_path="/var/lib/rediska/attachments")

    # Upload a file
    result = service.upload(
        file_data=content_bytes,
        filename="document.pdf",
        content_type="application/pdf"
    )
    print(f"Uploaded: {result.attachment_id}, SHA256: {result.sha256}")

    # Retrieve attachment
    attachment = service.get_by_id(result.attachment_id)
    file_path = service.get_file_path(result.attachment_id)
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import Attachment


# =============================================================================
# EXCEPTIONS
# =============================================================================


class AttachmentError(Exception):
    """Base exception for attachment operations."""
    pass


class FileTooLargeError(AttachmentError):
    """Raised when file exceeds maximum size limit."""
    pass


class InvalidMimeTypeError(AttachmentError):
    """Raised when file has disallowed MIME type."""
    pass


# =============================================================================
# CONSTANTS
# =============================================================================


# Maximum file size: 10MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    # Images
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",

    # Documents
    "application/pdf",
    "application/json",
    "text/plain",
    "text/html",
    "text/css",
    "text/csv",
    "text/markdown",

    # Archives (read-only, for received attachments)
    "application/zip",
    "application/gzip",

    # Audio/Video (for received media)
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "video/mp4",
    "video/webm",

    # Generic binary (fallback for unknown but safe)
    "application/octet-stream",
}

# Dangerous MIME types that are always rejected
BLOCKED_MIME_TYPES = {
    "application/x-msdownload",  # .exe
    "application/x-msdos-program",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-dosexec",
    "application/vnd.microsoft.portable-executable",
    "application/x-mach-binary",
    "application/x-sh",
    "application/x-shellscript",
    "text/x-python",
    "text/x-perl",
    "text/x-ruby",
}

# Image MIME types that support dimension extraction
IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

# Extension mapping from MIME types
MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/css": ".css",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "application/zip": ".zip",
    "application/gzip": ".gz",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/octet-stream": ".bin",
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class AttachmentUploadResult:
    """Result of a successful attachment upload."""

    attachment_id: int
    sha256: str
    storage_key: str
    size_bytes: int
    mime_type: str
    width_px: Optional[int] = None
    height_px: Optional[int] = None


# =============================================================================
# SERVICE
# =============================================================================


class AttachmentService:
    """Service for managing local attachment storage."""

    def __init__(
        self,
        db: Session,
        storage_path: str,
        max_size_bytes: int = MAX_FILE_SIZE_BYTES,
    ):
        """Initialize the attachment service.

        Args:
            db: SQLAlchemy session.
            storage_path: Base directory for file storage.
            max_size_bytes: Maximum allowed file size (default 10MB).
        """
        self.db = db
        self.storage_path = Path(storage_path)
        self.max_size_bytes = max_size_bytes

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        message_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> AttachmentUploadResult:
        """Upload a file and create an attachment record.

        Args:
            file_data: Raw file bytes.
            filename: Original filename.
            content_type: MIME type of the file.
            message_id: Optional message ID to link attachment to.
            username: Optional username to organize files by (e.g., conversation counterpart).

        Returns:
            AttachmentUploadResult with attachment details.

        Raises:
            FileTooLargeError: If file exceeds size limit.
            InvalidMimeTypeError: If MIME type is not allowed.
            ValueError: If file is empty.
        """
        # Validate file is not empty
        if not file_data:
            raise ValueError("File cannot be empty")

        # Validate file size
        if len(file_data) > self.max_size_bytes:
            raise FileTooLargeError(
                f"File size {len(file_data)} bytes exceeds maximum of "
                f"{self.max_size_bytes} bytes (10MB)"
            )

        # Validate MIME type
        if content_type in BLOCKED_MIME_TYPES:
            raise InvalidMimeTypeError(
                f"MIME type '{content_type}' is not allowed"
            )

        if content_type not in ALLOWED_MIME_TYPES:
            raise InvalidMimeTypeError(
                f"MIME type '{content_type}' is not in the allowlist"
            )

        # Compute SHA256 hash
        sha256_hash = hashlib.sha256(file_data).hexdigest()

        # Generate storage key (by username if provided, otherwise date-based)
        storage_key = self._generate_storage_key(filename, content_type, username)

        # Write file to disk
        file_path = self.storage_path / storage_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(file_data)

        # Extract image dimensions if applicable
        width_px, height_px = self._extract_image_dimensions(file_data, content_type)

        # Create database record
        attachment = Attachment(
            message_id=message_id,
            storage_backend="fs",
            storage_key=storage_key,
            sha256=sha256_hash,
            mime_type=content_type,
            size_bytes=len(file_data),
            width_px=width_px,
            height_px=height_px,
            remote_visibility="visible",
        )
        self.db.add(attachment)
        self.db.flush()

        return AttachmentUploadResult(
            attachment_id=attachment.id,
            sha256=sha256_hash,
            storage_key=storage_key,
            size_bytes=len(file_data),
            mime_type=content_type,
            width_px=width_px,
            height_px=height_px,
        )

    def get_by_id(self, attachment_id: int) -> Optional[Attachment]:
        """Get an attachment by its ID.

        Args:
            attachment_id: The attachment ID.

        Returns:
            Attachment record or None if not found.
        """
        return self.db.query(Attachment).filter_by(id=attachment_id).first()

    def get_by_sha256(self, sha256: str) -> Optional[Attachment]:
        """Get an attachment by its SHA256 hash.

        Args:
            sha256: The SHA256 hash hex string.

        Returns:
            Attachment record or None if not found.
        """
        return self.db.query(Attachment).filter_by(sha256=sha256).first()

    def get_file_path(self, attachment_id: int) -> Optional[str]:
        """Get the filesystem path for an attachment.

        Args:
            attachment_id: The attachment ID.

        Returns:
            Full filesystem path or None if not found.
        """
        attachment = self.get_by_id(attachment_id)
        if not attachment:
            return None

        file_path = self.storage_path / attachment.storage_key
        if not file_path.exists():
            return None

        return str(file_path)

    def _generate_storage_key(
        self,
        filename: str,
        content_type: str,
        username: Optional[str] = None,
    ) -> str:
        """Generate a unique storage key with directory structure.

        Format:
        - With username: users/{username}/{uuid}.ext
        - Without username: YYYY/MM/DD/{uuid}.ext (fallback for non-conversation files)

        Args:
            filename: Original filename.
            content_type: MIME type.
            username: Optional username to organize by.

        Returns:
            Storage key path.
        """
        # Get extension from MIME type or filename
        extension = self._get_safe_extension(filename, content_type)

        # Generate unique ID
        unique_id = uuid.uuid4().hex[:16]

        if username:
            # Sanitize username for filesystem (remove dangerous chars)
            safe_username = "".join(
                c for c in username if c.isalnum() or c in "-_"
            ).lower()
            if not safe_username:
                safe_username = "unknown"

            # Build path: users/{username}/{uuid}.ext
            storage_key = f"users/{safe_username}/{unique_id}{extension}"
        else:
            # Fallback: date-based path YYYY/MM/DD/uuid.ext
            now = datetime.now()
            storage_key = f"{now.year:04d}/{now.month:02d}/{now.day:02d}/{unique_id}{extension}"

        return storage_key

    def _get_safe_extension(self, filename: str, content_type: str) -> str:
        """Get a safe file extension.

        Prioritizes MIME type mapping over filename extension to prevent
        extension spoofing attacks.

        Args:
            filename: Original filename.
            content_type: MIME type.

        Returns:
            Safe file extension starting with '.'.
        """
        # Use MIME type mapping first (safer)
        if content_type in MIME_TO_EXTENSION:
            return MIME_TO_EXTENSION[content_type]

        # Fall back to filename extension if safe
        if filename:
            ext = Path(filename).suffix.lower()
            # Block dangerous extensions
            dangerous_extensions = {
                ".exe", ".bat", ".cmd", ".com", ".msi", ".dll",
                ".sh", ".bash", ".zsh", ".ps1", ".psm1",
                ".py", ".pyw", ".rb", ".pl", ".php",
                ".js", ".vbs", ".wsf", ".hta",
            }
            if ext and ext not in dangerous_extensions:
                return ext

        # Default to .bin for unknown types
        return ".bin"

    def _extract_image_dimensions(
        self,
        file_data: bytes,
        content_type: str,
    ) -> tuple[Optional[int], Optional[int]]:
        """Extract width and height from image data.

        Args:
            file_data: Raw image bytes.
            content_type: MIME type.

        Returns:
            Tuple of (width, height) or (None, None) if not an image
            or dimensions cannot be extracted.
        """
        if content_type not in IMAGE_MIME_TYPES:
            return None, None

        try:
            # Try to use PIL if available
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(file_data))
            return image.width, image.height
        except ImportError:
            # PIL not available, try manual parsing for common formats
            return self._extract_dimensions_manual(file_data, content_type)
        except Exception:
            # Any error during image parsing
            return None, None

    def _extract_dimensions_manual(
        self,
        file_data: bytes,
        content_type: str,
    ) -> tuple[Optional[int], Optional[int]]:
        """Manually extract image dimensions without PIL.

        Supports PNG and JPEG formats.

        Args:
            file_data: Raw image bytes.
            content_type: MIME type.

        Returns:
            Tuple of (width, height) or (None, None) if parsing fails.
        """
        try:
            if content_type == "image/png":
                # PNG: dimensions at bytes 16-23 in IHDR chunk
                if len(file_data) >= 24 and file_data[:8] == b'\x89PNG\r\n\x1a\n':
                    width = int.from_bytes(file_data[16:20], 'big')
                    height = int.from_bytes(file_data[20:24], 'big')
                    return width, height

            elif content_type == "image/jpeg":
                # JPEG: find SOF marker for dimensions
                i = 0
                while i < len(file_data) - 9:
                    if file_data[i] == 0xFF:
                        marker = file_data[i + 1]
                        # SOF0, SOF1, SOF2 markers
                        if marker in (0xC0, 0xC1, 0xC2):
                            height = int.from_bytes(file_data[i + 5:i + 7], 'big')
                            width = int.from_bytes(file_data[i + 7:i + 9], 'big')
                            return width, height
                        # Skip to next marker
                        if marker != 0xD8 and marker != 0xD9:
                            length = int.from_bytes(file_data[i + 2:i + 4], 'big')
                            i += 2 + length
                        else:
                            i += 2
                    else:
                        i += 1

            elif content_type == "image/gif":
                # GIF: dimensions at bytes 6-9
                if len(file_data) >= 10 and file_data[:6] in (b'GIF87a', b'GIF89a'):
                    width = int.from_bytes(file_data[6:8], 'little')
                    height = int.from_bytes(file_data[8:10], 'little')
                    return width, height

        except Exception:
            pass

        return None, None


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "AttachmentService",
    "AttachmentUploadResult",
    "AttachmentError",
    "FileTooLargeError",
    "InvalidMimeTypeError",
    "MAX_FILE_SIZE_BYTES",
    "ALLOWED_MIME_TYPES",
]
