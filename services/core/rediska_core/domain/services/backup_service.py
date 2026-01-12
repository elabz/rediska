"""Backup service for database dumps and attachments snapshots."""

import gzip
import hashlib
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from rediska_core.config import Settings


class BackupType(Enum):
    """Types of backups supported."""

    DATABASE = "database"
    ATTACHMENTS = "attachments"


@dataclass
class BackupResult:
    """Result of a backup operation."""

    success: bool
    backup_type: BackupType
    started_at: datetime
    completed_at: datetime = field(default_factory=datetime.utcnow)
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    checksum: Optional[str] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> int:
        """Calculate backup duration in seconds."""
        return int((self.completed_at - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "success": self.success,
            "backup_type": self.backup_type.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "checksum": self.checksum,
            "error": self.error,
        }


class BackupService:
    """Service for creating and managing backups."""

    def __init__(self, settings: Settings):
        """Initialize backup service with settings."""
        self.backups_path = settings.backups_path
        self.attachments_path = settings.attachments_path
        self._mysql_url = settings.mysql_url

    def _generate_backup_filename(self, backup_type: BackupType) -> str:
        """Generate a dated backup filename."""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")

        if backup_type == BackupType.DATABASE:
            return f"database_{timestamp}.sql.gz"
        elif backup_type == BackupType.ATTACHMENTS:
            return f"attachments_{timestamp}.tar.gz"
        else:
            raise ValueError(f"Unknown backup type: {backup_type}")

    def _calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    def _ensure_backup_directory(self) -> None:
        """Ensure backup directory exists."""
        Path(self.backups_path).mkdir(parents=True, exist_ok=True)

    def _write_checksum_file(self, backup_file_path: str, checksum: str) -> None:
        """Write checksum to companion file."""
        filename = Path(backup_file_path).name
        checksum_path = f"{backup_file_path}.sha256"

        with open(checksum_path, "w") as f:
            f.write(f"{checksum}  {filename}\n")

    def _parse_mysql_url(self) -> dict[str, Any]:
        """Parse MySQL URL into connection parameters."""
        # Handle SQLite URLs for testing
        if self._mysql_url.startswith("sqlite"):
            return {
                "host": None,
                "port": None,
                "user": None,
                "password": None,
                "database": ":memory:",
            }

        # Parse MySQL URL: mysql+pymysql://user:pass@host:port/database
        url = self._mysql_url.replace("mysql+pymysql://", "mysql://")
        url = url.replace("mysql+asyncmy://", "mysql://")
        parsed = urlparse(url)

        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "root",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/") if parsed.path else "rediska",
        }

    def _build_mysqldump_command(
        self, database: str, output_path: str
    ) -> list[str]:
        """Build mysqldump command with appropriate options."""
        params = self._parse_mysql_url()

        cmd = [
            "mysqldump",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--events",
            "--quick",
            "--lock-tables=false",
            f"--host={params['host']}",
            f"--port={params['port']}",
            f"--user={params['user']}",
            database,
        ]

        return cmd

    def dump_database(self) -> BackupResult:
        """Create a compressed MySQL database dump."""
        started_at = datetime.utcnow()

        try:
            self._ensure_backup_directory()

            params = self._parse_mysql_url()
            if params["host"] is None:
                # SQLite - can't dump with mysqldump
                return BackupResult(
                    success=False,
                    backup_type=BackupType.DATABASE,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    error="Cannot dump SQLite database with mysqldump",
                )

            filename = self._generate_backup_filename(BackupType.DATABASE)
            output_path = str(Path(self.backups_path) / filename)

            # Build command
            cmd = self._build_mysqldump_command(params["database"], output_path)

            # Set up environment with password
            env = os.environ.copy()
            if params["password"]:
                env["MYSQL_PWD"] = params["password"]

            # Create temporary uncompressed file
            temp_path = output_path.replace(".gz", "")

            # Run mysqldump
            with open(temp_path, "w") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                )

            if result.returncode != 0:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)

                return BackupResult(
                    success=False,
                    backup_type=BackupType.DATABASE,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    error=result.stderr or f"mysqldump failed with code {result.returncode}",
                )

            # Compress the dump
            with open(temp_path, "rb") as f_in:
                with gzip.open(output_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Remove temp file
            os.remove(temp_path)

            # Calculate checksum and file size
            checksum = self._calculate_checksum(output_path)
            file_size = os.path.getsize(output_path)

            # Write checksum file
            self._write_checksum_file(output_path, checksum)

            return BackupResult(
                success=True,
                backup_type=BackupType.DATABASE,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                file_path=output_path,
                file_size=file_size,
                checksum=checksum,
            )

        except Exception as e:
            return BackupResult(
                success=False,
                backup_type=BackupType.DATABASE,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                error=str(e),
            )

    def snapshot_attachments(self) -> BackupResult:
        """Create a compressed tarball of attachments directory."""
        started_at = datetime.utcnow()

        try:
            self._ensure_backup_directory()

            # Check source directory exists
            if not Path(self.attachments_path).exists():
                return BackupResult(
                    success=False,
                    backup_type=BackupType.ATTACHMENTS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    error=f"Attachments directory does not exist: {self.attachments_path}",
                )

            filename = self._generate_backup_filename(BackupType.ATTACHMENTS)
            output_path = str(Path(self.backups_path) / filename)

            # Create tarball
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(
                    self.attachments_path,
                    arcname=os.path.basename(self.attachments_path),
                )

            # Calculate checksum and file size
            checksum = self._calculate_checksum(output_path)
            file_size = os.path.getsize(output_path)

            # Write checksum file
            self._write_checksum_file(output_path, checksum)

            return BackupResult(
                success=True,
                backup_type=BackupType.ATTACHMENTS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                file_path=output_path,
                file_size=file_size,
                checksum=checksum,
            )

        except Exception as e:
            return BackupResult(
                success=False,
                backup_type=BackupType.ATTACHMENTS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                error=str(e),
            )

    def list_backups(
        self, backup_type: Optional[BackupType] = None
    ) -> list[dict[str, Any]]:
        """List available backup files."""
        backups = []
        backup_dir = Path(self.backups_path)

        if not backup_dir.exists():
            return backups

        patterns = []
        if backup_type is None or backup_type == BackupType.DATABASE:
            patterns.append("database_*.sql.gz")
        if backup_type is None or backup_type == BackupType.ATTACHMENTS:
            patterns.append("attachments_*.tar.gz")

        for pattern in patterns:
            for file_path in backup_dir.glob(pattern):
                # Skip checksum files
                if file_path.suffix == ".sha256":
                    continue

                # Read checksum if available
                checksum_file = Path(str(file_path) + ".sha256")
                checksum = None
                if checksum_file.exists():
                    checksum = checksum_file.read_text().split()[0]

                # Determine backup type from filename
                if file_path.name.startswith("database_"):
                    b_type = BackupType.DATABASE
                else:
                    b_type = BackupType.ATTACHMENTS

                backups.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "backup_type": b_type.value,
                    "file_size": file_path.stat().st_size,
                    "checksum": checksum,
                    "created_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                })

        # Sort by filename (which includes date) descending
        backups.sort(key=lambda x: x["filename"], reverse=True)

        return backups

    def cleanup_old_backups(
        self,
        retention_count: int = 7,
        backup_type: Optional[BackupType] = None,
    ) -> int:
        """Remove old backups beyond retention count."""
        removed = 0
        backup_dir = Path(self.backups_path)

        if not backup_dir.exists():
            return removed

        # Group backups by type
        db_backups = sorted(backup_dir.glob("database_*.sql.gz"), reverse=True)
        att_backups = sorted(backup_dir.glob("attachments_*.tar.gz"), reverse=True)

        def remove_old_files(files: list[Path], keep: int) -> int:
            count = 0
            for file_path in files[keep:]:
                file_path.unlink()
                # Also remove checksum file
                checksum_file = Path(str(file_path) + ".sha256")
                if checksum_file.exists():
                    checksum_file.unlink()
                count += 1
            return count

        if backup_type is None or backup_type == BackupType.DATABASE:
            removed += remove_old_files(db_backups, retention_count)

        if backup_type is None or backup_type == BackupType.ATTACHMENTS:
            removed += remove_old_files(att_backups, retention_count)

        return removed
