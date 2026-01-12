"""Restore test service for verifying backup integrity."""

import gzip
import hashlib
import os
import random
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from rediska_core.config import Settings

# Docker is optional - only needed when actually running restore tests
try:
    import docker
except ImportError:
    docker = None  # type: ignore


class IntegrityCheck(Enum):
    """Types of integrity checks to run on restored database."""

    TABLE_COUNT = "table_count"
    ROW_COUNTS = "row_counts"
    FOREIGN_KEYS = "foreign_keys"
    RECENT_DATA = "recent_data"
    INDEX_HEALTH = "index_health"


@dataclass
class IntegrityCheckResult:
    """Result of a single integrity check."""

    check_name: str
    passed: bool
    expected: Optional[str] = None
    actual: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "error": self.error,
        }


@dataclass
class RestoreTestResult:
    """Result of a backup restore test."""

    success: bool
    backup_file: str
    started_at: datetime
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    integrity_checks: list[IntegrityCheckResult] = field(default_factory=list)
    attachments_sampled: int = 0
    attachments_verified: int = 0
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> int:
        """Calculate test duration in seconds."""
        return int((self.completed_at - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "success": self.success,
            "backup_file": self.backup_file,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "integrity_checks": [check.to_dict() for check in self.integrity_checks],
            "attachments_sampled": self.attachments_sampled,
            "attachments_verified": self.attachments_verified,
            "error": self.error,
        }


class RestoreTestService:
    """Service for testing backup restoration."""

    # Expected tables in the database (for integrity checks)
    EXPECTED_TABLES = [
        "providers",
        "identities",
        "accounts",
        "conversations",
        "messages",
        "attachments",
        "leads",
        "audit_log",
        "jobs",
        "local_users",
        "user_sessions",
    ]

    # Docker configuration
    MYSQL_IMAGE = "mysql:8.0"
    MYSQL_ROOT_PASSWORD = "restore_test_password"
    CONTAINER_STARTUP_TIMEOUT = 60  # seconds

    def __init__(self, settings: Settings):
        """Initialize restore test service."""
        self.backups_path = settings.backups_path
        self.attachments_path = settings.attachments_path
        self._mysql_url = settings.mysql_url

    def find_latest_backup(self, backup_type: str) -> Optional[str]:
        """Find the latest backup file of the specified type.

        Args:
            backup_type: Either "database" or "attachments"

        Returns:
            Path to the latest backup file, or None if not found
        """
        backup_dir = Path(self.backups_path)
        if not backup_dir.exists():
            return None

        if backup_type == "database":
            pattern = "database_*.sql.gz"
        elif backup_type == "attachments":
            pattern = "attachments_*.tar.gz"
        else:
            raise ValueError(f"Unknown backup type: {backup_type}")

        files = sorted(backup_dir.glob(pattern), reverse=True)
        if not files:
            return None

        return str(files[0])

    def verify_backup_checksum(self, backup_file: str) -> bool:
        """Verify backup file checksum matches stored value.

        Args:
            backup_file: Path to the backup file

        Returns:
            True if checksum matches, False otherwise
        """
        checksum_file = f"{backup_file}.sha256"
        if not Path(checksum_file).exists():
            return False

        # Read stored checksum
        stored_line = Path(checksum_file).read_text().strip()
        stored_checksum = stored_line.split()[0]

        # Calculate actual checksum
        sha256_hash = hashlib.sha256()
        with open(backup_file, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        actual_checksum = sha256_hash.hexdigest()

        return stored_checksum == actual_checksum

    def _create_ephemeral_container(self) -> Any:
        """Create an ephemeral MySQL container for testing.

        Returns:
            Docker container object

        Raises:
            RuntimeError: If docker is not available
        """
        if docker is None:
            raise RuntimeError("Docker is not available. Install docker package to run restore tests.")

        client = docker.from_env()

        container = client.containers.run(
            self.MYSQL_IMAGE,
            detach=True,
            remove=True,
            environment={
                "MYSQL_ROOT_PASSWORD": self.MYSQL_ROOT_PASSWORD,
                "MYSQL_DATABASE": "rediska_restore_test",
            },
            ports={"3306/tcp": None},  # Random available port
            healthcheck={
                "test": ["CMD", "mysqladmin", "ping", "-h", "localhost"],
                "interval": 2000000000,  # 2 seconds in nanoseconds
                "timeout": 5000000000,
                "retries": 30,
            },
        )

        # Wait for container to be healthy
        start_time = time.time()
        while time.time() - start_time < self.CONTAINER_STARTUP_TIMEOUT:
            container.reload()
            if container.status == "running":
                # Check if MySQL is ready
                exit_code, _ = container.exec_run(
                    "mysqladmin ping -h localhost -uroot -p" + self.MYSQL_ROOT_PASSWORD
                )
                if exit_code == 0:
                    return container
            time.sleep(1)

        raise TimeoutError("MySQL container failed to start within timeout")

    def _cleanup_container(self, container: Any) -> None:
        """Stop and remove the ephemeral container.

        Args:
            container: Docker container object
        """
        try:
            container.stop(timeout=10)
        except Exception:
            pass

        try:
            container.remove(force=True)
        except Exception:
            pass

    def _import_database_dump(self, container: Any, dump_file: str) -> bool:
        """Import database dump into the container.

        Args:
            container: Docker container object
            dump_file: Path to the compressed SQL dump

        Returns:
            True if import succeeded, False otherwise
        """
        # Decompress the dump to a temp file
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            with gzip.open(dump_file, "rb") as f_in:
                shutil.copyfileobj(f_in, tmp)
            tmp_path = tmp.name

        try:
            # Copy dump to container
            with open(tmp_path, "rb") as f:
                data = f.read()

            container.put_archive("/tmp", self._create_tar_archive("dump.sql", data))

            # Import the dump
            exit_code, output = container.exec_run(
                f"mysql -uroot -p{self.MYSQL_ROOT_PASSWORD} rediska_restore_test < /tmp/dump.sql",
                demux=True,
            )

            return exit_code == 0
        finally:
            os.unlink(tmp_path)

    def _create_tar_archive(self, filename: str, content: bytes) -> bytes:
        """Create a tar archive containing a single file.

        Args:
            filename: Name for the file in the archive
            content: File content

        Returns:
            Tar archive as bytes
        """
        import io
        import tarfile as tf

        tar_stream = io.BytesIO()
        with tf.open(fileobj=tar_stream, mode="w") as tar:
            file_data = io.BytesIO(content)
            info = tf.TarInfo(name=filename)
            info.size = len(content)
            tar.addfile(info, file_data)

        tar_stream.seek(0)
        return tar_stream.read()

    def _build_integrity_queries(self) -> dict[IntegrityCheck, str]:
        """Build SQL queries for integrity checks.

        Returns:
            Dictionary mapping check types to SQL queries
        """
        return {
            IntegrityCheck.TABLE_COUNT: """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'rediska_restore_test'
            """,
            IntegrityCheck.ROW_COUNTS: """
                SELECT table_name, table_rows
                FROM information_schema.tables
                WHERE table_schema = 'rediska_restore_test'
                ORDER BY table_name
            """,
            IntegrityCheck.FOREIGN_KEYS: """
                SELECT COUNT(*) FROM information_schema.table_constraints
                WHERE constraint_type = 'FOREIGN KEY'
                AND table_schema = 'rediska_restore_test'
            """,
            IntegrityCheck.RECENT_DATA: """
                SELECT MAX(created_at) FROM messages
            """,
            IntegrityCheck.INDEX_HEALTH: """
                SELECT COUNT(*) FROM information_schema.statistics
                WHERE table_schema = 'rediska_restore_test'
            """,
        }

    def _run_integrity_check(
        self,
        container: Any,
        check: IntegrityCheck,
        query: str,
    ) -> IntegrityCheckResult:
        """Run a single integrity check against the container.

        Args:
            container: Docker container object
            check: The type of integrity check
            query: SQL query to execute

        Returns:
            IntegrityCheckResult with the outcome
        """
        try:
            exit_code, output = container.exec_run(
                f'mysql -uroot -p{self.MYSQL_ROOT_PASSWORD} -N -e "{query}"',
                demux=True,
            )

            if exit_code != 0:
                return IntegrityCheckResult(
                    check_name=check.value,
                    passed=False,
                    error=f"Query failed with exit code {exit_code}",
                )

            stdout = output[0] if output[0] else b""
            actual = stdout.decode().strip()

            return IntegrityCheckResult(
                check_name=check.value,
                passed=True,
                actual=actual,
            )

        except Exception as e:
            return IntegrityCheckResult(
                check_name=check.value,
                passed=False,
                error=str(e),
            )

    def _sample_attachments(
        self, attachments_backup: str, sample_size: int = 10
    ) -> tuple[int, int]:
        """Sample and verify attachments from backup.

        Args:
            attachments_backup: Path to attachments tarball
            sample_size: Number of files to sample

        Returns:
            Tuple of (sampled_count, verified_count)
        """
        if not Path(attachments_backup).exists():
            return 0, 0

        try:
            with tarfile.open(attachments_backup, "r:gz") as tar:
                members = [m for m in tar.getmembers() if m.isfile()]

                if not members:
                    return 0, 0

                # Sample random files
                sample = random.sample(members, min(sample_size, len(members)))
                verified = 0

                for member in sample:
                    try:
                        f = tar.extractfile(member)
                        if f:
                            # Read file to verify it's not corrupted
                            content = f.read()
                            if len(content) > 0:
                                verified += 1
                    except Exception:
                        pass

                return len(sample), verified

        except Exception:
            return 0, 0

    def run_restore_test(self) -> RestoreTestResult:
        """Run a full restore test.

        This method:
        1. Finds the latest database backup
        2. Verifies the backup checksum
        3. Creates an ephemeral MySQL container
        4. Imports the database dump
        5. Runs integrity checks
        6. Samples attachments
        7. Cleans up the container

        Returns:
            RestoreTestResult with the outcome
        """
        started_at = datetime.now(timezone.utc)
        container = None
        db_backup: Optional[str] = None

        try:
            # Find latest backups
            db_backup = self.find_latest_backup("database")
            if not db_backup:
                return RestoreTestResult(
                    success=False,
                    backup_file="",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error="No database backup found",
                )

            # Verify checksum
            if not self.verify_backup_checksum(db_backup):
                return RestoreTestResult(
                    success=False,
                    backup_file=db_backup,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error="Backup checksum verification failed",
                )

            # Create ephemeral container
            container = self._create_ephemeral_container()

            # Import database dump
            if not self._import_database_dump(container, db_backup):
                return RestoreTestResult(
                    success=False,
                    backup_file=db_backup,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error="Failed to import database dump",
                )

            # Run integrity checks
            queries = self._build_integrity_queries()
            integrity_results = []
            all_passed = True

            for check, query in queries.items():
                result = self._run_integrity_check(container, check, query)
                integrity_results.append(result)
                if not result.passed:
                    all_passed = False

            # Sample attachments
            att_backup = self.find_latest_backup("attachments")
            sampled, verified = 0, 0
            if att_backup:
                sampled, verified = self._sample_attachments(att_backup)

            return RestoreTestResult(
                success=all_passed and (sampled == 0 or verified > 0),
                backup_file=db_backup,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                integrity_checks=integrity_results,
                attachments_sampled=sampled,
                attachments_verified=verified,
            )

        except Exception as e:
            return RestoreTestResult(
                success=False,
                backup_file=db_backup or "",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error=str(e),
            )

        finally:
            if container:
                self._cleanup_container(container)
