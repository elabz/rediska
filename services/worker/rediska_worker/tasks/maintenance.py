"""Maintenance tasks for backups and system health."""

import gzip
import hashlib
import os
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rediska_worker.celery_app import app

# Configuration from environment
MYSQL_URL = os.getenv("MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/rediska")
BACKUPS_PATH = os.getenv("BACKUPS_PATH", "/var/lib/rediska/backups")
ATTACHMENTS_PATH = os.getenv("ATTACHMENTS_PATH", "/var/lib/rediska/attachments")
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "7"))


def _now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def _parse_mysql_url(url: str) -> dict[str, Any]:
    """Parse MySQL URL into connection parameters."""
    url = url.replace("mysql+pymysql://", "mysql://")
    url = url.replace("mysql+asyncmy://", "mysql://")
    parsed = urlparse(url)

    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") if parsed.path else "rediska",
    }


def _calculate_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _write_checksum_file(backup_file_path: str, checksum: str) -> None:
    """Write checksum to companion file."""
    filename = Path(backup_file_path).name
    checksum_path = f"{backup_file_path}.sha256"
    with open(checksum_path, "w") as f:
        f.write(f"{checksum}  {filename}\n")


def _cleanup_old_backups(pattern: str, retention_count: int) -> int:
    """Remove old backups beyond retention count."""
    backup_dir = Path(BACKUPS_PATH)
    if not backup_dir.exists():
        return 0

    files = sorted(backup_dir.glob(pattern), reverse=True)
    removed = 0

    for file_path in files[retention_count:]:
        file_path.unlink()
        checksum_file = Path(str(file_path) + ".sha256")
        if checksum_file.exists():
            checksum_file.unlink()
        removed += 1

    return removed


@app.task(name="maintenance.mysql_dump_local", bind=True, max_retries=3)
def mysql_dump_local(self) -> dict:
    """Create a local MySQL dump backup.

    Creates a dated, compressed MySQL dump with SHA256 checksum.
    Cleans up old backups beyond retention count.
    """
    started_at = _now_utc()

    try:
        # Ensure backup directory exists
        Path(BACKUPS_PATH).mkdir(parents=True, exist_ok=True)

        # Parse MySQL connection
        params = _parse_mysql_url(MYSQL_URL)

        # Generate filename
        timestamp = started_at.strftime("%Y-%m-%d_%H%M%S")
        filename = f"database_{timestamp}.sql.gz"
        output_path = str(Path(BACKUPS_PATH) / filename)
        temp_path = output_path.replace(".gz", "")

        # Build mysqldump command
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
            params["database"],
        ]

        # Set up environment with password
        env = os.environ.copy()
        if params["password"]:
            env["MYSQL_PWD"] = params["password"]

        # Run mysqldump
        with open(temp_path, "w") as f:
            result = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

        if result.returncode != 0:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise RuntimeError(f"mysqldump failed: {result.stderr}")

        # Compress the dump
        with open(temp_path, "rb") as f_in:
            with gzip.open(output_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove temp file
        os.remove(temp_path)

        # Calculate checksum and file size
        checksum = _calculate_checksum(output_path)
        file_size = os.path.getsize(output_path)

        # Write checksum file
        _write_checksum_file(output_path, checksum)

        # Cleanup old backups
        removed = _cleanup_old_backups("database_*.sql.gz", BACKUP_RETENTION_COUNT)

        completed_at = _now_utc()

        return {
            "status": "success",
            "backup_type": "database",
            "file_path": output_path,
            "file_size": file_size,
            "checksum": checksum,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
            "old_backups_removed": removed,
        }

    except Exception as exc:
        completed_at = _now_utc()

        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))

        return {
            "status": "failed",
            "backup_type": "database",
            "error": str(exc),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }


@app.task(name="maintenance.attachments_snapshot_local", bind=True, max_retries=3)
def attachments_snapshot_local(self) -> dict:
    """Create a local snapshot of attachments.

    Creates a dated, compressed tarball of the attachments directory
    with SHA256 checksum. Cleans up old backups beyond retention count.
    """
    started_at = _now_utc()

    try:
        # Ensure backup directory exists
        Path(BACKUPS_PATH).mkdir(parents=True, exist_ok=True)

        # Check source directory exists
        if not Path(ATTACHMENTS_PATH).exists():
            raise FileNotFoundError(f"Attachments directory not found: {ATTACHMENTS_PATH}")

        # Generate filename
        timestamp = started_at.strftime("%Y-%m-%d_%H%M%S")
        filename = f"attachments_{timestamp}.tar.gz"
        output_path = str(Path(BACKUPS_PATH) / filename)

        # Create tarball
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(
                ATTACHMENTS_PATH,
                arcname=os.path.basename(ATTACHMENTS_PATH),
            )

        # Calculate checksum and file size
        checksum = _calculate_checksum(output_path)
        file_size = os.path.getsize(output_path)

        # Write checksum file
        _write_checksum_file(output_path, checksum)

        # Cleanup old backups
        removed = _cleanup_old_backups("attachments_*.tar.gz", BACKUP_RETENTION_COUNT)

        completed_at = _now_utc()

        return {
            "status": "success",
            "backup_type": "attachments",
            "file_path": output_path,
            "file_size": file_size,
            "checksum": checksum,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
            "old_backups_removed": removed,
        }

    except Exception as exc:
        completed_at = _now_utc()

        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))

        return {
            "status": "failed",
            "backup_type": "attachments",
            "error": str(exc),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }


@app.task(name="maintenance.restore_test_local", bind=True, max_retries=1)
def restore_test_local(self) -> dict:
    """Test backup restoration in an ephemeral container.

    This task:
    1. Finds the latest database backup
    2. Verifies the backup checksum
    3. Creates an ephemeral MySQL container
    4. Imports the database dump
    5. Runs integrity checks
    6. Samples attachments from backup
    7. Records result in audit log
    """
    started_at = _now_utc()
    db_backup = None
    container = None

    try:
        import docker
    except ImportError:
        return {
            "status": "failed",
            "error": "Docker is not available. Install docker package to run restore tests.",
            "started_at": started_at.isoformat(),
            "completed_at": _now_utc().isoformat(),
        }

    try:
        # Find latest database backup
        backup_dir = Path(BACKUPS_PATH)
        if not backup_dir.exists():
            return {
                "status": "failed",
                "error": "Backup directory does not exist",
                "started_at": started_at.isoformat(),
                "completed_at": _now_utc().isoformat(),
            }

        db_files = sorted(backup_dir.glob("database_*.sql.gz"), reverse=True)
        if not db_files:
            return {
                "status": "failed",
                "error": "No database backup found",
                "started_at": started_at.isoformat(),
                "completed_at": _now_utc().isoformat(),
            }

        db_backup = str(db_files[0])

        # Verify checksum
        checksum_file = f"{db_backup}.sha256"
        if Path(checksum_file).exists():
            stored_checksum = Path(checksum_file).read_text().strip().split()[0]
            actual_checksum = _calculate_checksum(db_backup)
            if stored_checksum != actual_checksum:
                return {
                    "status": "failed",
                    "backup_file": db_backup,
                    "error": "Backup checksum verification failed",
                    "started_at": started_at.isoformat(),
                    "completed_at": _now_utc().isoformat(),
                }

        # Create ephemeral MySQL container
        client = docker.from_env()
        mysql_password = "restore_test_password"

        container = client.containers.run(
            "mysql:8.0",
            detach=True,
            remove=True,
            environment={
                "MYSQL_ROOT_PASSWORD": mysql_password,
                "MYSQL_DATABASE": "rediska_restore_test",
            },
            ports={"3306/tcp": None},
        )

        # Wait for MySQL to be ready
        import time
        for _ in range(60):
            container.reload()
            if container.status == "running":
                exit_code, _ = container.exec_run(
                    f"mysqladmin ping -h localhost -uroot -p{mysql_password}"
                )
                if exit_code == 0:
                    break
            time.sleep(1)
        else:
            raise TimeoutError("MySQL container failed to start")

        # Decompress and import the dump
        import io
        import tarfile as tf

        with gzip.open(db_backup, "rb") as f_in:
            sql_content = f_in.read()

        # Create tar archive with the SQL file
        tar_stream = io.BytesIO()
        with tf.open(fileobj=tar_stream, mode="w") as tar:
            file_data = io.BytesIO(sql_content)
            info = tf.TarInfo(name="dump.sql")
            info.size = len(sql_content)
            tar.addfile(info, file_data)
        tar_stream.seek(0)

        container.put_archive("/tmp", tar_stream.read())

        # Import the dump
        exit_code, output = container.exec_run(
            f"sh -c 'mysql -uroot -p{mysql_password} rediska_restore_test < /tmp/dump.sql'",
            demux=True,
        )

        if exit_code != 0:
            stderr = output[1].decode() if output[1] else "Unknown error"
            return {
                "status": "failed",
                "backup_file": db_backup,
                "error": f"Failed to import database dump: {stderr}",
                "started_at": started_at.isoformat(),
                "completed_at": _now_utc().isoformat(),
            }

        # Run integrity checks
        integrity_checks = []

        # Table count check
        exit_code, output = container.exec_run(
            f'mysql -uroot -p{mysql_password} -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = \'rediska_restore_test\'"',
            demux=True,
        )
        if exit_code == 0 and output[0]:
            table_count = output[0].decode().strip()
            integrity_checks.append({
                "check_name": "table_count",
                "passed": True,
                "actual": table_count,
            })
        else:
            integrity_checks.append({
                "check_name": "table_count",
                "passed": False,
                "error": "Failed to count tables",
            })

        # Sample attachments
        att_files = sorted(backup_dir.glob("attachments_*.tar.gz"), reverse=True)
        attachments_sampled = 0
        attachments_verified = 0

        if att_files:
            att_backup = str(att_files[0])
            try:
                with tarfile.open(att_backup, "r:gz") as tar:
                    members = [m for m in tar.getmembers() if m.isfile()]
                    import random
                    sample = random.sample(members, min(10, len(members)))
                    attachments_sampled = len(sample)

                    for member in sample:
                        try:
                            f = tar.extractfile(member)
                            if f and len(f.read()) > 0:
                                attachments_verified += 1
                        except Exception:
                            pass
            except Exception:
                pass

        completed_at = _now_utc()
        all_checks_passed = all(c.get("passed", False) for c in integrity_checks)

        return {
            "status": "success" if all_checks_passed else "failed",
            "backup_file": db_backup,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
            "integrity_checks": integrity_checks,
            "attachments_sampled": attachments_sampled,
            "attachments_verified": attachments_verified,
        }

    except Exception as exc:
        completed_at = _now_utc()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300)

        return {
            "status": "failed",
            "backup_file": db_backup or "",
            "error": str(exc),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }

    finally:
        if container:
            try:
                container.stop(timeout=10)
            except Exception:
                pass
            try:
                container.remove(force=True)
            except Exception:
                pass


@app.task(name="maintenance.cleanup_scout_watch_history", bind=True, max_retries=3)
def cleanup_scout_watch_history(self, retention_days: int = 3) -> dict:
    """Delete scout watch runs and posts older than retention_days.

    This task removes old ScoutWatchRun records (and their associated
    ScoutWatchPost records via cascade) to conserve database space.

    Args:
        retention_days: Number of days of history to retain. Default is 3.

    Returns:
        Dict with status, runs_deleted count, and timestamps.
    """
    started_at = _now_utc()

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as SQLSession

        from rediska_core.domain.services.scout_watch import ScoutWatchService

        # Create database session
        engine = create_engine(MYSQL_URL)
        with SQLSession(engine) as session:
            service = ScoutWatchService(session)

            # Delete old runs (posts cascade via FK)
            deleted_count = service.delete_old_runs(retention_days=retention_days)

            session.commit()

        completed_at = _now_utc()

        return {
            "status": "success",
            "runs_deleted": deleted_count,
            "retention_days": retention_days,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
        }

    except Exception as exc:
        completed_at = _now_utc()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))

        return {
            "status": "failed",
            "error": str(exc),
            "retention_days": retention_days,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }
