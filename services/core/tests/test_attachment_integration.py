"""
Integration tests for Epic 5.1 - Attachment API endpoints.

Tests cover:
1. POST /attachments/upload - multipart file upload
2. GET /attachments/{id} - streaming download with auth
3. GET /attachments/{id}/meta - metadata retrieval
"""

import tempfile
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import Attachment, LocalUser


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
async def auth_client(test_app, db_session):
    """An HTTP client whose requests are authenticated.

    Every /attachments/* route depends on `CurrentUser`. The shared `client`
    fixture carries no session cookie, so without this override the tests below
    only ever observe a 401 and never reach the upload/download logic.
    """
    user = LocalUser(username="attachment_tester", password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.flush()

    test_app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def sample_image_bytes():
    """Create a minimal valid PNG image."""
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


@pytest.fixture
def temp_attachments_path(test_settings):
    """Point the attachment route's storage at a throwaway directory.

    The route builds its service from `get_settings()` (the real, env-backed
    settings), so mutating `test_settings` alone has no effect -- the module
    lookup has to be patched too.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        original_path = test_settings.attachments_path
        test_settings.attachments_path = tmpdir
        with patch(
            "rediska_core.api.routes.attachment.get_settings",
            return_value=test_settings,
        ):
            yield tmpdir
        test_settings.attachments_path = original_path


# =============================================================================
# UPLOAD ENDPOINT TESTS
# =============================================================================


class TestUploadEndpoint:
    """Tests for POST /attachments/upload endpoint."""

    @pytest.mark.asyncio
    async def test_upload_returns_attachment_info(
        self, auth_client, db_session, sample_image_bytes, temp_attachments_path
    ):
        """Successful upload should return attachment details."""
        files = {"file": ("test.png", sample_image_bytes, "image/png")}

        response = await auth_client.post(
            "/attachments/upload",
            files=files,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["mime_type"] == "image/png"
        assert data["size_bytes"] == len(sample_image_bytes)
        assert len(data["sha256"]) == 64
        # 1x1 PNG -- dimensions are extracted server-side.
        assert data["width_px"] == 1
        assert data["height_px"] == 1

        stored = db_session.query(Attachment).filter_by(id=data["id"]).one()
        assert stored.sha256 == data["sha256"]
        assert stored.storage_backend == "fs"

    @pytest.mark.asyncio
    async def test_upload_requires_authentication(
        self, client, sample_image_bytes
    ):
        """Upload should fail without authentication."""
        files = {"file": ("test.png", sample_image_bytes, "image/png")}

        response = await client.post(
            "/attachments/upload",
            files=files,
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_rejects_too_large_file(
        self, auth_client, temp_attachments_path
    ):
        """Files over 10MB should be rejected."""
        # Create 11MB of data
        large_data = b"x" * (11 * 1024 * 1024)
        files = {"file": ("large.bin", large_data, "application/octet-stream")}

        response = await auth_client.post(
            "/attachments/upload",
            files=files,
        )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_rejects_invalid_mime_type(
        self, auth_client, temp_attachments_path
    ):
        """Dangerous MIME types should be rejected."""
        files = {"file": ("malware.exe", b"fake exe", "application/x-msdownload")}

        response = await auth_client.post(
            "/attachments/upload",
            files=files,
        )

        assert response.status_code == 415


# =============================================================================
# DOWNLOAD ENDPOINT TESTS
# =============================================================================


class TestDownloadEndpoint:
    """Tests for GET /attachments/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_download_returns_404_for_missing(
        self, auth_client, temp_attachments_path
    ):
        """Download of non-existent attachment should return 404."""
        response = await auth_client.get("/attachments/99999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_download_returns_uploaded_bytes(
        self, auth_client, sample_image_bytes, temp_attachments_path
    ):
        """An uploaded attachment can be downloaded back byte-for-byte."""
        upload = await auth_client.post(
            "/attachments/upload",
            files={"file": ("test.png", sample_image_bytes, "image/png")},
        )
        assert upload.status_code == 201
        attachment_id = upload.json()["id"]

        response = await auth_client.get(f"/attachments/{attachment_id}")

        assert response.status_code == 200
        assert response.content == sample_image_bytes
        assert response.headers["content-type"] == "image/png"

    @pytest.mark.asyncio
    async def test_download_requires_authentication(
        self, client
    ):
        """Download should require authentication."""
        response = await client.get("/attachments/1")

        assert response.status_code == 401


# =============================================================================
# METADATA ENDPOINT TESTS
# =============================================================================


class TestMetadataEndpoint:
    """Tests for GET /attachments/{id}/meta endpoint."""

    @pytest.mark.asyncio
    async def test_metadata_returns_404_for_missing(
        self, auth_client, temp_attachments_path
    ):
        """Metadata for non-existent attachment should return 404."""
        response = await auth_client.get("/attachments/99999/meta")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_metadata_returns_uploaded_details(
        self, auth_client, sample_image_bytes, temp_attachments_path
    ):
        """Metadata mirrors the upload response without streaming the file."""
        upload = await auth_client.post(
            "/attachments/upload",
            files={"file": ("test.png", sample_image_bytes, "image/png")},
        )
        assert upload.status_code == 201
        uploaded = upload.json()

        response = await auth_client.get(f"/attachments/{uploaded['id']}/meta")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == uploaded["id"]
        assert data["sha256"] == uploaded["sha256"]
        assert data["mime_type"] == "image/png"
        assert data["size_bytes"] == len(sample_image_bytes)
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_metadata_requires_authentication(
        self, client
    ):
        """Metadata endpoint should require authentication."""
        response = await client.get("/attachments/1/meta")

        assert response.status_code == 401
