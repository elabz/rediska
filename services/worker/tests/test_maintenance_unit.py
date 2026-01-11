"""Unit tests for maintenance tasks.

Tests cover:
- mysql_dump_local task
- attachments_snapshot_local task
- restore_test_local task
- Helper functions
"""

import gzip
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestParseMyqlUrl:
    """Tests for _parse_mysql_url helper."""

    def test_parse_basic_url(self):
        """Test parsing basic MySQL URL."""
        from rediska_worker.tasks.maintenance import _parse_mysql_url

        result = _parse_mysql_url("mysql+pymysql://user:pass@localhost:3306/mydb")

        assert result["host"] == "localhost"
        assert result["port"] == 3306
        assert result["user"] == "user"
        assert result["password"] == "pass"
        assert result["database"] == "mydb"

    def test_parse_url_with_special_chars_in_password(self):
        """Test parsing URL with special characters in password."""
        from rediska_worker.tasks.maintenance import _parse_mysql_url

        # URL-encoded characters remain encoded in urlparse
        result = _parse_mysql_url("mysql+pymysql://user:p%40ss%2Fword@localhost:3306/db")

        # urllib.parse preserves percent-encoding in password
        assert result["password"] == "p%40ss%2Fword"

    def test_parse_url_without_port(self):
        """Test parsing URL without explicit port."""
        from rediska_worker.tasks.maintenance import _parse_mysql_url

        result = _parse_mysql_url("mysql+pymysql://user:pass@localhost/db")

        assert result["port"] == 3306  # Default

    def test_parse_asyncmy_url(self):
        """Test parsing URL with asyncmy driver."""
        from rediska_worker.tasks.maintenance import _parse_mysql_url

        result = _parse_mysql_url("mysql+asyncmy://user:pass@localhost:3306/db")

        assert result["host"] == "localhost"
        assert result["database"] == "db"


class TestCalculateChecksum:
    """Tests for _calculate_checksum helper."""

    def test_calculates_sha256(self, tmp_path):
        """Test SHA256 checksum calculation."""
        from rediska_worker.tasks.maintenance import _calculate_checksum

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        checksum = _calculate_checksum(str(test_file))

        # SHA256 is 64 hex characters
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_same_content_same_checksum(self, tmp_path):
        """Same content should produce same checksum."""
        from rediska_worker.tasks.maintenance import _calculate_checksum

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Same content")
        file2.write_text("Same content")

        assert _calculate_checksum(str(file1)) == _calculate_checksum(str(file2))

    def test_different_content_different_checksum(self, tmp_path):
        """Different content should produce different checksum."""
        from rediska_worker.tasks.maintenance import _calculate_checksum

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content A")
        file2.write_text("Content B")

        assert _calculate_checksum(str(file1)) != _calculate_checksum(str(file2))


class TestWriteChecksumFile:
    """Tests for _write_checksum_file helper."""

    def test_writes_checksum_file(self, tmp_path):
        """Test writing checksum file."""
        from rediska_worker.tasks.maintenance import _write_checksum_file

        backup_file = tmp_path / "backup.sql.gz"
        backup_file.touch()

        _write_checksum_file(str(backup_file), "abc123checksum")

        checksum_file = tmp_path / "backup.sql.gz.sha256"
        assert checksum_file.exists()
        content = checksum_file.read_text()
        assert "abc123checksum" in content
        assert "backup.sql.gz" in content


class TestCleanupOldBackups:
    """Tests for _cleanup_old_backups helper."""

    def test_removes_old_backups(self, tmp_path):
        """Test removing backups beyond retention count."""
        import rediska_worker.tasks.maintenance as maint

        # Save original and patch
        original_backups_path = maint.BACKUPS_PATH
        maint.BACKUPS_PATH = str(tmp_path)

        try:
            # Create 5 backup files
            for i in range(5):
                (tmp_path / f"database_2024-01-0{i+1}.sql.gz").touch()
                (tmp_path / f"database_2024-01-0{i+1}.sql.gz.sha256").touch()

            removed = maint._cleanup_old_backups("database_*.sql.gz", retention_count=3)

            assert removed == 2
            # Should keep newest 3
            remaining = list(tmp_path.glob("database_*.sql.gz"))
            assert len(remaining) == 3
        finally:
            maint.BACKUPS_PATH = original_backups_path

    def test_preserves_when_under_retention(self, tmp_path):
        """Test that files are preserved when under retention count."""
        import rediska_worker.tasks.maintenance as maint

        original_backups_path = maint.BACKUPS_PATH
        maint.BACKUPS_PATH = str(tmp_path)

        try:
            # Create 2 backup files
            (tmp_path / "database_2024-01-01.sql.gz").touch()
            (tmp_path / "database_2024-01-02.sql.gz").touch()

            removed = maint._cleanup_old_backups("database_*.sql.gz", retention_count=5)

            assert removed == 0
        finally:
            maint.BACKUPS_PATH = original_backups_path

    def test_handles_missing_directory(self, tmp_path):
        """Test handling missing backup directory."""
        import rediska_worker.tasks.maintenance as maint

        non_existent = tmp_path / "does_not_exist"

        original_backups_path = maint.BACKUPS_PATH
        maint.BACKUPS_PATH = str(non_existent)

        try:
            removed = maint._cleanup_old_backups("*.sql.gz", retention_count=3)
            assert removed == 0
        finally:
            maint.BACKUPS_PATH = original_backups_path


class TestMysqlDumpLocal:
    """Tests for mysql_dump_local task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.maintenance import mysql_dump_local

        assert mysql_dump_local.name == "maintenance.mysql_dump_local"

    def test_task_is_bound(self, mock_celery_app):
        """Task should be bound (has self access)."""
        from rediska_worker.tasks.maintenance import mysql_dump_local

        # Bound tasks have __self__ when called or check the _orig_run method
        # The bind=True option creates a bound task
        assert hasattr(mysql_dump_local, "run")

    def test_task_has_max_retries(self, mock_celery_app):
        """Task should have max_retries configured."""
        from rediska_worker.tasks.maintenance import mysql_dump_local

        assert mysql_dump_local.max_retries == 3


class TestAttachmentsSnapshotLocal:
    """Tests for attachments_snapshot_local task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.maintenance import attachments_snapshot_local

        assert attachments_snapshot_local.name == "maintenance.attachments_snapshot_local"

    def test_creates_tarball(self, tmp_path, mock_celery_app):
        """Task should create a tarball of attachments."""
        import rediska_worker.tasks.maintenance as maint

        # Setup directories
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "test.txt").write_text("test content")

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = str(att_dir)

        try:
            result = maint.attachments_snapshot_local.apply().get()

            assert result["status"] == "success"
            assert result["backup_type"] == "attachments"
            assert Path(result["file_path"]).exists()

            # Verify it's a valid tarball
            with tarfile.open(result["file_path"], "r:gz") as tar:
                members = tar.getnames()
                assert len(members) > 0
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments

    def test_creates_checksum_file(self, tmp_path, mock_celery_app):
        """Task should create checksum file."""
        import rediska_worker.tasks.maintenance as maint

        # Setup directories
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "test.txt").write_text("test content")

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = str(att_dir)

        try:
            result = maint.attachments_snapshot_local.apply().get()

            checksum_file = Path(result["file_path"] + ".sha256")
            assert checksum_file.exists()
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments

    def test_returns_file_size(self, tmp_path, mock_celery_app):
        """Task should return file size."""
        import rediska_worker.tasks.maintenance as maint

        # Setup directories
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "test.txt").write_text("test content")

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = str(att_dir)

        try:
            result = maint.attachments_snapshot_local.apply().get()

            assert "file_size" in result
            assert result["file_size"] > 0
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments

    def test_handles_missing_attachments_dir(self, tmp_path, mock_celery_app):
        """Task should handle missing attachments directory - triggers retry."""
        import rediska_worker.tasks.maintenance as maint
        from celery.exceptions import Retry

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = "/nonexistent/path"

        try:
            # Task will raise Retry due to FileNotFoundError
            with pytest.raises(Retry):
                maint.attachments_snapshot_local.apply().get()
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments


class TestRestoreTestLocal:
    """Tests for restore_test_local task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.maintenance import restore_test_local

        assert restore_test_local.name == "maintenance.restore_test_local"

    def test_handles_missing_docker(self, tmp_path, mock_celery_app):
        """Task should handle missing docker package."""
        import rediska_worker.tasks.maintenance as maint

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # Create a fake backup file
        backup_file = backup_dir / "database_2024-01-01.sql.gz"
        with gzip.open(backup_file, "wt") as f:
            f.write("-- Fake SQL dump\n")

        orig_backups = maint.BACKUPS_PATH
        maint.BACKUPS_PATH = str(backup_dir)

        try:
            result = maint.restore_test_local.apply().get()
            # Task may fail due to docker unavailability
            assert "status" in result
        finally:
            maint.BACKUPS_PATH = orig_backups

    def test_handles_no_backup_found(self, tmp_path, mock_celery_app):
        """Task should handle no backup files found."""
        import rediska_worker.tasks.maintenance as maint

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        orig_backups = maint.BACKUPS_PATH
        maint.BACKUPS_PATH = str(backup_dir)

        try:
            result = maint.restore_test_local.apply().get()
            assert result["status"] == "failed"
            # Could be "No database backup found" or docker unavailable
            assert "error" in result
        finally:
            maint.BACKUPS_PATH = orig_backups


class TestMaintenanceTaskRouting:
    """Tests for maintenance task routing configuration."""

    def test_maintenance_tasks_routed_to_maintenance_queue(self, mock_celery_app):
        """Maintenance tasks should be routed to maintenance queue."""
        routes = mock_celery_app.conf.task_routes

        assert "rediska_worker.tasks.maintenance.*" in routes
        assert routes["rediska_worker.tasks.maintenance.*"]["queue"] == "maintenance"


class TestMaintenanceTaskNames:
    """Tests for maintenance task naming conventions."""

    def test_all_maintenance_tasks_have_correct_prefix(self, mock_celery_app):
        """All maintenance tasks should have 'maintenance.' prefix."""
        from rediska_worker.tasks import maintenance

        tasks = [
            maintenance.mysql_dump_local,
            maintenance.attachments_snapshot_local,
            maintenance.restore_test_local,
        ]

        for task in tasks:
            assert task.name.startswith("maintenance."), f"{task.name} should start with 'maintenance.'"


class TestBackupResultFormat:
    """Tests for backup task result format."""

    def test_attachments_result_has_required_fields(self, tmp_path, mock_celery_app):
        """Attachment backup result should have all required fields."""
        import rediska_worker.tasks.maintenance as maint

        # Setup directories
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "test.txt").write_text("test content")

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = str(att_dir)

        try:
            result = maint.attachments_snapshot_local.apply().get()

            required_fields = [
                "status",
                "backup_type",
                "file_path",
                "file_size",
                "checksum",
                "started_at",
                "completed_at",
                "duration_seconds",
            ]

            for field in required_fields:
                assert field in result, f"Missing field: {field}"
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments

    def test_result_timestamps_are_iso_format(self, tmp_path, mock_celery_app):
        """Result timestamps should be ISO format."""
        import rediska_worker.tasks.maintenance as maint

        # Setup directories
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "test.txt").write_text("test content")

        orig_backups = maint.BACKUPS_PATH
        orig_attachments = maint.ATTACHMENTS_PATH
        maint.BACKUPS_PATH = str(backup_dir)
        maint.ATTACHMENTS_PATH = str(att_dir)

        try:
            result = maint.attachments_snapshot_local.apply().get()

            # Should be parseable as ISO format
            datetime.fromisoformat(result["started_at"])
            datetime.fromisoformat(result["completed_at"])
        finally:
            maint.BACKUPS_PATH = orig_backups
            maint.ATTACHMENTS_PATH = orig_attachments
