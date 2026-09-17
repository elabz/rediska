"""Inbox export / import / clear API routes.

Implements the `inbox-export`, `inbox-import`, and `inbox-clear` capabilities:

- POST /inbox/export           - queue an export, returns a job id
- GET  /inbox/exports          - list generated dump files
- GET  /inbox/exports/{name}   - download a dump file
- POST /inbox/import           - upload a dump and queue a restore
- POST /inbox/clear            - clear the inbox (typed confirmation required)
- GET  /inbox/jobs/{job_id}    - poll progress of any of the above
"""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from celery import Celery
from celery.result import AsyncResult
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.config import get_settings
from rediska_core.domain.models import AuditLog
from rediska_core.domain.services.inbox_transfer import (
    InboxImportService,
    InvalidDumpError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox-transfer"])

EXPORT_SUBDIR = "inbox-exports"
TRANSFER_QUEUE = "transfer"

# The phrase a user must type to authorize a clear. Kept deliberately awkward
# so it cannot be produced by an accidental keypress or a stray form submit.
CLEAR_CONFIRMATION_PHRASE = "CLEAR MY INBOX"


# =============================================================================
# Schemas
# =============================================================================


class ExportRequest(BaseModel):
    """Request to queue an inbox export."""

    filename: Optional[str] = Field(
        default=None, description="Optional dump filename; defaults to a timestamped name"
    )


class JobQueuedResponse(BaseModel):
    """A background transfer job was accepted."""

    job_id: str
    status: str
    message: str


class ExportFileInfo(BaseModel):
    """A dump file available for download."""

    filename: str
    size_bytes: int
    created_at: datetime


class ExportListResponse(BaseModel):
    """Available dump files, newest first."""

    exports: list[ExportFileInfo]


class ClearRequest(BaseModel):
    """Request to clear the inbox."""

    confirmation: str = Field(
        description=f"Must be exactly {CLEAR_CONFIRMATION_PHRASE!r} to proceed"
    )


class TransferJobStatusResponse(BaseModel):
    """Progress/result of a transfer job."""

    job_id: str
    status: str
    stage: Optional[str] = None
    done: Optional[int] = None
    total: Optional[int] = None
    percent: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# =============================================================================
# Helpers
# =============================================================================


def get_celery_app() -> Celery:
    """Get a Celery app instance for dispatching transfer tasks."""
    settings = get_settings()
    return Celery(
        "rediska",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )


def export_dir() -> Path:
    """Directory holding generated dumps. Shared with the worker via a volume."""
    return Path(get_settings().backups_path) / EXPORT_SUBDIR


def _resolve_export_path(filename: str) -> Path:
    """Resolve a dump filename inside the export directory.

    Rejects any name that would escape the directory, so a crafted filename
    cannot be used to read arbitrary files off the container filesystem.
    """
    if filename != Path(filename).name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid export filename",
        )

    base = export_dir().resolve()
    candidate = (base / filename).resolve()
    if not candidate.is_relative_to(base):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid export filename",
        )
    return candidate


def _audit(
    db: DBSession,
    action_type: str,
    request_json: dict[str, Any],
    response_json: dict[str, Any],
    result: str = "ok",
) -> None:
    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type=action_type,
            result=result,
            entity_type="inbox",
            request_json=request_json,
            response_json=response_json,
        )
    )
    db.commit()


# =============================================================================
# Export
# =============================================================================


@router.post(
    "/export",
    response_model=JobQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an inbox export",
    description="Queue a background job that dumps all inbox content to a JSON file.",
)
async def trigger_export(
    request: ExportRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Queue an inbox export job."""
    celery_app = get_celery_app()
    task = celery_app.send_task(
        "inbox.export",
        kwargs={"filename": request.filename},
        queue=TRANSFER_QUEUE,
    )

    _audit(
        db,
        "inbox.export.trigger",
        {"filename": request.filename},
        {"job_id": task.id},
    )

    return JobQueuedResponse(
        job_id=task.id,
        status="queued",
        message="Export job queued. The dump will be available for download when it completes.",
    )


@router.get(
    "/exports",
    response_model=ExportListResponse,
    summary="List available dump files",
    description="List generated inbox dumps, newest first.",
)
async def list_exports(current_user: CurrentUser):
    """List available dump files."""
    directory = export_dir()
    if not directory.is_dir():
        return ExportListResponse(exports=[])

    entries = []
    for path in directory.glob("*.json"):
        stat = path.stat()
        entries.append(
            ExportFileInfo(
                filename=path.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    entries.sort(key=lambda entry: entry.created_at, reverse=True)
    return ExportListResponse(exports=entries)


@router.get(
    "/exports/{filename}",
    summary="Download a dump file",
    description="Download a previously generated inbox dump.",
)
async def download_export(filename: str, current_user: CurrentUser):
    """Download a dump file."""
    path = _resolve_export_path(filename)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export file not found",
        )

    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=path.name,
    )


# =============================================================================
# Import
# =============================================================================


@router.post(
    "/import",
    response_model=JobQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Import an inbox dump",
    description="Upload a dump file and queue a background restore. "
    "The dump is validated before the job is queued, so a malformed file "
    "is rejected immediately rather than failing in the background.",
)
async def trigger_import(
    current_user: CurrentUser,
    db: DBSession,
    file: UploadFile = File(..., description="A JSON dump produced by the export endpoint"),
):
    """Validate an uploaded dump and queue a restore job."""
    staging_dir = export_dir() / "incoming"
    staging_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_name = Path(file.filename or "upload.json").name
    staged_path = staging_dir / f"{timestamp}_{safe_name}"

    try:
        with open(staged_path, "wb") as handle:
            shutil.copyfileobj(file.file, handle)
    except OSError as exc:
        logger.exception("Failed to stage uploaded dump")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not store uploaded file: {exc}",
        ) from exc
    finally:
        await file.close()

    # Validate up front so the user gets a real error instead of a failed job.
    try:
        InboxImportService.load(staged_path)
    except InvalidDumpError as exc:
        staged_path.unlink(missing_ok=True)
        _audit(
            db,
            "inbox.import.trigger",
            {"filename": safe_name},
            {"error": str(exc)},
            result="error",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dump file: {exc}",
        ) from exc

    celery_app = get_celery_app()
    task = celery_app.send_task(
        "inbox.import",
        kwargs={"dump_path": str(staged_path)},
        queue=TRANSFER_QUEUE,
    )

    _audit(
        db,
        "inbox.import.trigger",
        {"filename": safe_name, "dump_path": str(staged_path)},
        {"job_id": task.id},
    )

    return JobQueuedResponse(
        job_id=task.id,
        status="queued",
        message="Import job queued. Existing content is skipped; only new items are restored.",
    )


# =============================================================================
# Clear
# =============================================================================


@router.post(
    "/clear",
    response_model=JobQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Clear all inbox content",
    description="Delete all conversations, messages, and message-linked attachment "
    "records. Providers, identities, credentials, external accounts, leads, and "
    "profile data are preserved, and attachment files stay on disk so a later "
    "import restores working references. Requires a typed confirmation phrase.",
)
async def trigger_clear(
    request: ClearRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Queue an inbox clear job after verifying the confirmation phrase."""
    if request.confirmation != CLEAR_CONFIRMATION_PHRASE:
        _audit(
            db,
            "inbox.clear.trigger",
            {"confirmation_provided": bool(request.confirmation)},
            {"error": "confirmation phrase mismatch"},
            result="error",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clear requires the exact confirmation phrase {CLEAR_CONFIRMATION_PHRASE!r}",
        )

    celery_app = get_celery_app()
    task = celery_app.send_task(
        "inbox.clear",
        kwargs={"confirm": True},
        queue=TRANSFER_QUEUE,
    )

    _audit(db, "inbox.clear.trigger", {"confirmed": True}, {"job_id": task.id})

    return JobQueuedResponse(
        job_id=task.id,
        status="queued",
        message="Clear job queued. Attachment files remain on disk and can be restored by import.",
    )


# =============================================================================
# Progress
# =============================================================================


@router.get(
    "/jobs/{job_id}",
    response_model=TransferJobStatusResponse,
    summary="Get transfer job progress",
    description="Poll the progress or result of an export, import, or clear job.",
)
async def get_transfer_job_status(job_id: str, current_user: CurrentUser):
    """Report progress for a transfer job."""
    celery_app = get_celery_app()
    result = AsyncResult(job_id, app=celery_app)

    if result.state == "PROGRESS":
        meta = result.info if isinstance(result.info, dict) else {}
        done = meta.get("done")
        total = meta.get("total")
        percent = meta.get("percent")
        if percent is None and done is not None and total:
            percent = round(done / total * 100, 1)

        return TransferJobStatusResponse(
            job_id=job_id,
            status="running",
            stage=meta.get("stage"),
            done=done,
            total=total,
            percent=percent,
        )

    if not result.ready():
        return TransferJobStatusResponse(job_id=job_id, status="pending")

    if result.successful():
        payload = result.result if isinstance(result.result, dict) else {}
        return TransferJobStatusResponse(
            job_id=job_id,
            status="completed",
            percent=100.0,
            result=payload,
        )

    return TransferJobStatusResponse(
        job_id=job_id,
        status="failed",
        error=str(result.result),
    )
