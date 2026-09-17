"""Unit tests for backup restore test service."""

import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Check if docker is available
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from rediska_core.domain.services.restore_service import (
    RestoreTestService,
    RestoreTestResult,
    IntegrityCheck,
    IntegrityCheckResult,
)


class TestRestoreTestResult:
    """Tests for RestoreTestResult dataclass."""

    def test_duration_seconds(self):
        """Test calculating restore test duration."""
        result = RestoreTestResult(
            success=True,
            backup_file="/backups/test.sql.gz",
            started_at=datetime(2024, 1, 15, 5, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2024, 1, 15, 5, 10, 30, tzinfo=timezone.utc),
        )

        assert result.duration_seconds == 630  # 10 minutes 30 seconds

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = RestoreTestResult(
            success=True,
            backup_file="/backups/test.sql.gz",
            started_at=datetime(2024, 1, 15, 5, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2024, 1, 15, 5, 5, 0, tzinfo=timezone.utc),
            integrity_checks=[
                IntegrityCheckResult(
                    check_name="table_count",
                    passed=True,
                    expected="15",
                    actual="15",
                ),
            ],
        )

        result_dict = result.to_dict()

        # Assert values, not just key presence: to_dict() feeds the audit log, so a
        # derived duration and nested check serialization are the real contract.
        assert result_dict["success"] is True
        assert result_dict["backup_file"] == "/backups/test.sql.gz"
        assert result_dict["duration_seconds"] == 300
        assert result_dict["integrity_checks"] == [
            {
                "check_name": "table_count",
                "passed": True,
                "expected": "15",
                "actual": "15",
                "error": None,
            }
        ]


class TestRestoreTestService:
    """Tests for RestoreTestService."""

    @pytest.fixture
    def restore_service(self, test_settings):
        """Create a RestoreTestService instance for testing."""
        return RestoreTestService(test_settings)

    @pytest.fixture
    def temp_backup_dir(self):
        """Create a temporary backup directory with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample backup files
            (Path(tmpdir) / "database_2024-01-15_030000.sql.gz").write_bytes(b"db dump 1")
            (Path(tmpdir) / "database_2024-01-14_030000.sql.gz").write_bytes(b"db dump 2")
            (Path(tmpdir) / "database_2024-01-15_030000.sql.gz.sha256").write_text(
                "abc123  database_2024-01-15_030000.sql.gz"
            )

            # Create attachments backup
            att_path = Path(tmpdir) / "attachments_2024-01-15_040000.tar.gz"
            with tarfile.open(att_path, "w:gz") as tar:
                # Create temp files to add
                with tempfile.NamedTemporaryFile(delete=False) as f:
                    f.write(b"test attachment")
                    # Must flush before tar.add: otherwise the bytes are still in the
                    # Python buffer and the archived member is 0 bytes, which
                    # _sample_attachments counts as unverified.
                    f.flush()
                    tar.add(f.name, arcname="attachments/test.jpg")

            yield tmpdir

    def test_init_with_settings(self, test_settings):
        """Test RestoreTestService initialization."""
        service = RestoreTestService(test_settings)

        assert service.backups_path == test_settings.backups_path

    def test_find_latest_database_backup(self, restore_service, temp_backup_dir):
        """Test finding the latest database backup."""
        restore_service.backups_path = temp_backup_dir

        latest = restore_service.find_latest_backup("database")

        assert latest is not None
        assert "2024-01-15" in latest
        assert latest.endswith(".sql.gz")

    def test_find_latest_attachments_backup(self, restore_service, temp_backup_dir):
        """Test finding the latest attachments backup."""
        restore_service.backups_path = temp_backup_dir

        latest = restore_service.find_latest_backup("attachments")

        assert latest is not None
        assert "attachments" in latest
        assert latest.endswith(".tar.gz")

    def test_find_latest_backup_no_backups(self, restore_service):
        """Test finding backup when none exist."""
        with tempfile.TemporaryDirectory() as empty_dir:
            restore_service.backups_path = empty_dir

            latest = restore_service.find_latest_backup("database")

            assert latest is None

    def test_verify_backup_checksum(self, restore_service, temp_backup_dir):
        """Test verifying backup checksum."""
        restore_service.backups_path = temp_backup_dir
        backup_file = str(Path(temp_backup_dir) / "database_2024-01-15_030000.sql.gz")

        # The checksum won't match since we wrote fake data
        # but we can test the method exists and runs
        result = restore_service.verify_backup_checksum(backup_file)

        # Result should be False since checksum doesn't match fake data
        assert result is False

    def test_verify_backup_checksum_no_checksum_file(self, restore_service, temp_backup_dir):
        """Test verifying backup when checksum file is missing."""
        restore_service.backups_path = temp_backup_dir
        backup_file = str(Path(temp_backup_dir) / "database_2024-01-14_030000.sql.gz")

        result = restore_service.verify_backup_checksum(backup_file)

        assert result is False

    @pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker not installed")
    @patch("rediska_core.domain.services.restore_service.docker")
    def test_create_ephemeral_container(self, mock_docker_module, restore_service):
        """Test creating an ephemeral MySQL container."""
        mock_client = MagicMock()
        mock_docker_module.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.id = "test-container-id"
        mock_container.status = "running"
        # Make exec_run return success for MySQL ping
        mock_container.exec_run.return_value = (0, b"")
        mock_client.containers.run.return_value = mock_container

        container = restore_service._create_ephemeral_container()

        assert container is not None
        mock_client.containers.run.assert_called_once()

    def test_cleanup_container(self, restore_service):
        """Test cleaning up ephemeral container."""
        mock_container = MagicMock()

        restore_service._cleanup_container(mock_container)

        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()

    def test_build_integrity_queries(self, restore_service):
        """Test building integrity check SQL queries."""
        queries = restore_service._build_integrity_queries()

        assert len(queries) > 0
        assert IntegrityCheck.TABLE_COUNT in queries
        assert IntegrityCheck.ROW_COUNTS in queries

    def test_run_integrity_check_table_count(self, restore_service):
        """Test running table count integrity check."""
        mock_container = MagicMock()

        # Mock exec_run to return table count (stdout, stderr tuple)
        mock_container.exec_run.return_value = (0, (b"15\n", None))

        result = restore_service._run_integrity_check(
            mock_container,
            IntegrityCheck.TABLE_COUNT,
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'rediska'",
        )

        assert result.check_name == "table_count"
        assert result.actual == "15"

    def test_sample_attachments(self, restore_service, temp_backup_dir):
        """Test sampling attachments from backup."""
        restore_service.backups_path = temp_backup_dir
        att_backup = str(Path(temp_backup_dir) / "attachments_2024-01-15_040000.tar.gz")

        sampled, verified = restore_service._sample_attachments(att_backup, sample_size=5)

        # The fixture tarball holds exactly one non-empty file, so both counts must
        # be 1. _sample_attachments swallows every error and returns (0, 0), which
        # a >= 0 assertion would happily accept from an unreadable tarball.
        assert (sampled, verified) == (1, 1)

    def test_sample_attachments_missing_backup_returns_zero(self, restore_service, tmp_path):
        """A missing tarball yields (0, 0) rather than raising."""
        sampled, verified = restore_service._sample_attachments(
            str(tmp_path / "does_not_exist.tar.gz"), sample_size=5
        )

        assert (sampled, verified) == (0, 0)


class TestRestoreTestServiceIntegration:
    """Integration tests for RestoreTestService."""

    @pytest.fixture
    def restore_service_with_dirs(self, test_settings):
        """Create RestoreTestService with real temporary directories."""
        with tempfile.TemporaryDirectory() as backup_dir:
            test_settings.backups_path = backup_dir

            # Create sample database backup
            db_backup = Path(backup_dir) / "database_2024-01-15_030000.sql.gz"
            import gzip
            with gzip.open(db_backup, "wb") as f:
                f.write(b"-- MySQL dump\nCREATE TABLE test (id INT);")

            # Calculate real checksum
            import hashlib
            with open(db_backup, "rb") as f:
                checksum = hashlib.sha256(f.read()).hexdigest()
            (Path(backup_dir) / "database_2024-01-15_030000.sql.gz.sha256").write_text(
                f"{checksum}  database_2024-01-15_030000.sql.gz"
            )

            yield RestoreTestService(test_settings)

    def test_verify_checksum_with_valid_file(self, restore_service_with_dirs):
        """Test checksum verification with valid file."""
        service = restore_service_with_dirs
        backup_file = service.find_latest_backup("database")

        result = service.verify_backup_checksum(backup_file)

        assert result is True

    def test_full_backup_discovery(self, restore_service_with_dirs):
        """Test discovering all backup components."""
        service = restore_service_with_dirs

        db_backup = service.find_latest_backup("database")

        assert db_backup is not None
        assert Path(db_backup).exists()


class TestRestoreTestResultAudit:
    """Tests for audit logging of restore test results."""

    def test_failed_result_includes_error(self):
        """Test that failed result includes error for audit."""
        result = RestoreTestResult(
            success=False,
            backup_file="/backups/test.sql.gz",
            started_at=datetime(2024, 1, 15, 5, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2024, 1, 15, 5, 0, 30, tzinfo=timezone.utc),
            error="Container failed to start",
        )

        result_dict = result.to_dict()

        assert result_dict["error"] == "Container failed to start"

    def test_integrity_check_failures_included(self):
        """Test that integrity check failures are included in result."""
        result = RestoreTestResult(
            success=False,
            backup_file="/backups/test.sql.gz",
            started_at=datetime(2024, 1, 15, 5, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2024, 1, 15, 5, 5, 0, tzinfo=timezone.utc),
            integrity_checks=[
                IntegrityCheckResult(
                    check_name="table_count",
                    passed=False,
                    expected="15",
                    actual="10",
                    error="Missing 5 tables",
                ),
            ],
        )

        result_dict = result.to_dict()

        assert len(result_dict["integrity_checks"]) == 1
        assert result_dict["integrity_checks"][0]["passed"] is False
        assert "Missing 5 tables" in result_dict["integrity_checks"][0]["error"]
