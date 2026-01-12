"""Unit tests for maintenance backup tasks."""

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from rediska_core.domain.services.backup_service import (
    BackupService,
    BackupResult,
    BackupType,
)


class TestBackupResult:
    """Tests for BackupResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful backup result."""
        result = BackupResult(
            success=True,
            backup_type=BackupType.DATABASE,
            file_path="/backups/db_2024-01-15_030000.sql.gz",
            file_size=1024000,
            checksum="abc123def456",
            started_at=datetime(2024, 1, 15, 3, 0, 0),
            completed_at=datetime(2024, 1, 15, 3, 5, 0),
        )

        assert result.success is True
        assert result.backup_type == BackupType.DATABASE
        assert result.file_path == "/backups/db_2024-01-15_030000.sql.gz"
        assert result.file_size == 1024000
        assert result.checksum == "abc123def456"

    def test_create_failure_result(self):
        """Test creating a failed backup result."""
        result = BackupResult(
            success=False,
            backup_type=BackupType.DATABASE,
            error="Connection refused",
            started_at=datetime(2024, 1, 15, 3, 0, 0),
            completed_at=datetime(2024, 1, 15, 3, 0, 5),
        )

        assert result.success is False
        assert result.error == "Connection refused"
        assert result.file_path is None
        assert result.file_size is None

    def test_backup_duration(self):
        """Test calculating backup duration."""
        result = BackupResult(
            success=True,
            backup_type=BackupType.DATABASE,
            file_path="/backups/test.sql.gz",
            started_at=datetime(2024, 1, 15, 3, 0, 0),
            completed_at=datetime(2024, 1, 15, 3, 5, 30),
        )

        assert result.duration_seconds == 330  # 5 minutes 30 seconds


class TestBackupType:
    """Tests for BackupType enum."""

    def test_database_type(self):
        """Test database backup type."""
        assert BackupType.DATABASE.value == "database"

    def test_attachments_type(self):
        """Test attachments backup type."""
        assert BackupType.ATTACHMENTS.value == "attachments"


class TestBackupService:
    """Tests for BackupService."""

    @pytest.fixture
    def backup_service(self, test_settings):
        """Create a BackupService instance for testing."""
        return BackupService(test_settings)

    @pytest.fixture
    def temp_backup_dir(self):
        """Create a temporary backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def temp_attachments_dir(self):
        """Create a temporary attachments directory with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some sample attachment files
            (Path(tmpdir) / "file1.jpg").write_bytes(b"image data 1")
            (Path(tmpdir) / "file2.png").write_bytes(b"image data 2")
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "file3.pdf").write_bytes(b"pdf data")
            yield tmpdir

    def test_init_with_settings(self, test_settings):
        """Test BackupService initialization with settings."""
        service = BackupService(test_settings)

        assert service.backups_path == test_settings.backups_path
        assert service.attachments_path == test_settings.attachments_path

    def test_generate_backup_filename_database(self, backup_service):
        """Test generating database backup filename."""
        with patch("rediska_core.domain.services.backup_service.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2024, 1, 15, 3, 0, 0)

            filename = backup_service._generate_backup_filename(BackupType.DATABASE)

            assert filename == "database_2024-01-15_030000.sql.gz"

    def test_generate_backup_filename_attachments(self, backup_service):
        """Test generating attachments backup filename."""
        with patch("rediska_core.domain.services.backup_service.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2024, 1, 15, 3, 0, 0)

            filename = backup_service._generate_backup_filename(BackupType.ATTACHMENTS)

            assert filename == "attachments_2024-01-15_030000.tar.gz"

    def test_calculate_checksum(self, backup_service, temp_backup_dir):
        """Test calculating file checksum."""
        # Create a test file
        test_file = Path(temp_backup_dir) / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        checksum = backup_service._calculate_checksum(str(test_file))

        expected_checksum = hashlib.sha256(test_content).hexdigest()
        assert checksum == expected_checksum

    def test_calculate_checksum_file_not_found(self, backup_service):
        """Test checksum calculation with non-existent file."""
        with pytest.raises(FileNotFoundError):
            backup_service._calculate_checksum("/nonexistent/file.txt")

    def test_ensure_backup_directory_creates_dir(self, backup_service, temp_backup_dir):
        """Test that backup directory is created if it doesn't exist."""
        new_dir = Path(temp_backup_dir) / "new_backup_dir"
        backup_service.backups_path = str(new_dir)

        backup_service._ensure_backup_directory()

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_ensure_backup_directory_exists(self, backup_service, temp_backup_dir):
        """Test that existing backup directory is handled correctly."""
        backup_service.backups_path = temp_backup_dir

        # Should not raise
        backup_service._ensure_backup_directory()

        assert Path(temp_backup_dir).exists()

    @patch("subprocess.run")
    def test_dump_database_success(self, mock_run, backup_service, temp_backup_dir):
        """Test successful database dump."""
        backup_service.backups_path = temp_backup_dir
        # Set MySQL URL to enable database dump
        backup_service._mysql_url = "mysql+pymysql://user:pass@localhost:3306/testdb"

        # Create a mock successful result
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        # Create a fake dump file to simulate mysqldump output
        with patch.object(backup_service, "_generate_backup_filename") as mock_filename:
            mock_filename.return_value = "database_test.sql.gz"
            # Mock the file creation that happens during dump
            temp_sql = Path(temp_backup_dir) / "database_test.sql"
            temp_sql.write_text("-- MySQL dump")

            result = backup_service.dump_database()

        assert result.success is True
        assert result.backup_type == BackupType.DATABASE

    @patch("subprocess.run")
    def test_dump_database_failure(self, mock_run, backup_service, temp_backup_dir):
        """Test database dump failure."""
        backup_service.backups_path = temp_backup_dir
        # Set MySQL URL to enable database dump
        backup_service._mysql_url = "mysql+pymysql://user:pass@localhost:3306/testdb"

        # Mock a failed mysqldump
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Access denied for user"
        )

        result = backup_service.dump_database()

        assert result.success is False
        assert "Access denied" in result.error

    @patch("subprocess.run")
    def test_dump_database_exception(self, mock_run, backup_service, temp_backup_dir):
        """Test database dump with exception."""
        backup_service.backups_path = temp_backup_dir
        # Set MySQL URL to enable database dump
        backup_service._mysql_url = "mysql+pymysql://user:pass@localhost:3306/testdb"

        mock_run.side_effect = Exception("Connection refused")

        result = backup_service.dump_database()

        assert result.success is False
        assert "Connection refused" in result.error

    def test_snapshot_attachments_success(
        self, backup_service, temp_backup_dir, temp_attachments_dir
    ):
        """Test successful attachments snapshot."""
        backup_service.backups_path = temp_backup_dir
        backup_service.attachments_path = temp_attachments_dir

        result = backup_service.snapshot_attachments()

        assert result.success is True
        assert result.backup_type == BackupType.ATTACHMENTS
        assert result.file_path is not None
        assert Path(result.file_path).exists()
        assert result.file_size > 0
        assert result.checksum is not None

    def test_snapshot_attachments_empty_directory(self, backup_service, temp_backup_dir):
        """Test attachments snapshot with empty directory."""
        backup_service.backups_path = temp_backup_dir

        with tempfile.TemporaryDirectory() as empty_dir:
            backup_service.attachments_path = empty_dir

            result = backup_service.snapshot_attachments()

            # Should succeed even with empty directory
            assert result.success is True

    def test_snapshot_attachments_nonexistent_directory(self, backup_service, temp_backup_dir):
        """Test attachments snapshot with non-existent source directory."""
        backup_service.backups_path = temp_backup_dir
        backup_service.attachments_path = "/nonexistent/path"

        result = backup_service.snapshot_attachments()

        assert result.success is False
        assert "not found" in result.error.lower() or "does not exist" in result.error.lower()

    def test_write_checksum_file(self, backup_service, temp_backup_dir):
        """Test writing checksum to companion file."""
        backup_file = Path(temp_backup_dir) / "backup.sql.gz"
        backup_file.write_bytes(b"test content")
        checksum = "abc123def456"

        backup_service._write_checksum_file(str(backup_file), checksum)

        checksum_file = Path(temp_backup_dir) / "backup.sql.gz.sha256"
        assert checksum_file.exists()
        assert checksum_file.read_text().strip() == f"{checksum}  backup.sql.gz"

    def test_list_backups(self, backup_service, temp_backup_dir):
        """Test listing available backups."""
        backup_service.backups_path = temp_backup_dir

        # Create some backup files
        (Path(temp_backup_dir) / "database_2024-01-15_030000.sql.gz").write_bytes(b"db1")
        (Path(temp_backup_dir) / "database_2024-01-14_030000.sql.gz").write_bytes(b"db2")
        (Path(temp_backup_dir) / "attachments_2024-01-15_030000.tar.gz").write_bytes(b"att1")

        backups = backup_service.list_backups()

        assert len(backups) == 3
        # Should be sorted by date descending
        assert "2024-01-15" in backups[0]["filename"]

    def test_list_backups_filter_by_type(self, backup_service, temp_backup_dir):
        """Test listing backups filtered by type."""
        backup_service.backups_path = temp_backup_dir

        # Create some backup files
        (Path(temp_backup_dir) / "database_2024-01-15_030000.sql.gz").write_bytes(b"db1")
        (Path(temp_backup_dir) / "database_2024-01-14_030000.sql.gz").write_bytes(b"db2")
        (Path(temp_backup_dir) / "attachments_2024-01-15_030000.tar.gz").write_bytes(b"att1")

        db_backups = backup_service.list_backups(backup_type=BackupType.DATABASE)

        assert len(db_backups) == 2
        assert all("database" in b["filename"] for b in db_backups)

    def test_cleanup_old_backups(self, backup_service, temp_backup_dir):
        """Test cleaning up old backups beyond retention limit."""
        backup_service.backups_path = temp_backup_dir

        # Create backup files with different dates
        for i in range(10):
            day = 15 - i
            (Path(temp_backup_dir) / f"database_2024-01-{day:02d}_030000.sql.gz").write_bytes(b"db")
            (Path(temp_backup_dir) / f"database_2024-01-{day:02d}_030000.sql.gz.sha256").write_text("checksum")

        # Keep only 7 backups
        removed = backup_service.cleanup_old_backups(retention_count=7)

        assert removed == 3
        remaining = list(Path(temp_backup_dir).glob("*.sql.gz"))
        assert len(remaining) == 7

    def test_cleanup_old_backups_nothing_to_remove(self, backup_service, temp_backup_dir):
        """Test cleanup when fewer backups than retention limit."""
        backup_service.backups_path = temp_backup_dir

        # Create only 3 backup files
        for i in range(3):
            day = 15 - i
            (Path(temp_backup_dir) / f"database_2024-01-{day:02d}_030000.sql.gz").write_bytes(b"db")

        removed = backup_service.cleanup_old_backups(retention_count=7)

        assert removed == 0
        remaining = list(Path(temp_backup_dir).glob("*.sql.gz"))
        assert len(remaining) == 3


class TestMySQLDumpCommand:
    """Tests for MySQL dump command generation."""

    @pytest.fixture
    def backup_service(self, test_settings):
        """Create a BackupService instance for testing."""
        return BackupService(test_settings)

    def test_build_mysqldump_command(self, backup_service):
        """Test building mysqldump command with correct parameters."""
        cmd = backup_service._build_mysqldump_command("test_db", "/path/to/output.sql.gz")

        assert "mysqldump" in cmd[0] or "mysqldump" in " ".join(cmd)
        assert "--single-transaction" in cmd
        assert "--routines" in cmd
        assert "--triggers" in cmd

    def test_mysqldump_command_excludes_password_in_args(self, backup_service):
        """Test that password is not passed as command line argument."""
        cmd = backup_service._build_mysqldump_command("test_db", "/path/to/output.sql.gz")

        # Password should be passed via environment or config file, not command line
        assert "--password" not in " ".join(cmd) or "--password=" not in " ".join(cmd)


class TestBackupServiceIntegration:
    """Integration tests for BackupService requiring external dependencies."""

    @pytest.fixture
    def backup_service_with_dirs(self, test_settings):
        """Create BackupService with real temporary directories."""
        with tempfile.TemporaryDirectory() as backup_dir:
            with tempfile.TemporaryDirectory() as attachments_dir:
                test_settings.backups_path = backup_dir
                test_settings.attachments_path = attachments_dir

                # Create some test attachments
                (Path(attachments_dir) / "test1.jpg").write_bytes(b"test image 1")
                (Path(attachments_dir) / "test2.pdf").write_bytes(b"test pdf")

                yield BackupService(test_settings)

    def test_full_attachments_backup_flow(self, backup_service_with_dirs):
        """Test complete attachments backup workflow."""
        service = backup_service_with_dirs

        # Perform backup
        result = service.snapshot_attachments()

        assert result.success is True
        assert result.backup_type == BackupType.ATTACHMENTS
        assert result.file_path is not None
        assert result.checksum is not None

        # Verify checksum file was created
        checksum_file = Path(result.file_path + ".sha256")
        assert checksum_file.exists()

        # Verify checksum matches
        stored_checksum = checksum_file.read_text().split()[0]
        assert stored_checksum == result.checksum

    def test_backup_result_to_dict(self, backup_service_with_dirs):
        """Test converting backup result to dictionary for storage."""
        result = backup_service_with_dirs.snapshot_attachments()

        result_dict = result.to_dict()

        assert "success" in result_dict
        assert "backup_type" in result_dict
        assert "file_path" in result_dict
        assert "checksum" in result_dict
        assert "started_at" in result_dict
        assert "completed_at" in result_dict
