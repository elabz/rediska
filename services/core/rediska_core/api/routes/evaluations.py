"""API routes for human evaluation of agent decisions.

Endpoints:
- POST /evaluations               record a verdict (audit: evaluation.record)
- GET  /evaluations               list evaluations for one subject
- GET  /evaluations/queue         unevaluated subjects to review
- GET  /evaluations/summary       agreement metrics
- GET  /evaluations/export        labelled dataset as JSONL (audit: evaluation.export)
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.evaluations import (
    EVALUABLE_DIMENSIONS,
    REASON_TAGS,
    EvaluationCreate,
    EvaluationListResponse,
    EvaluationResponse,
    EvaluationSummary,
    QueueResponse,
)
from rediska_core.domain.services.analysis_evaluation import (
    AnalysisEvaluationService,
    EvaluationSubjectNotFound,
    EvaluationValidationError,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("/vocabulary")
async def get_vocabulary(current_user: CurrentUser) -> dict:
    """Controlled reason-tag vocabulary and evaluable dimensions."""
    return {"reason_tags": list(REASON_TAGS), "dimensions": list(EVALUABLE_DIMENSIONS)}


@router.post("", response_model=EvaluationResponse, status_code=status.HTTP_201_CREATED)
async def record_evaluation(
    payload: EvaluationCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    """Record a human verdict on the final recommendation or one dimension."""
    service = AnalysisEvaluationService(db)
    try:
        row = service.record(payload, created_by=current_user.username or "user")
    except EvaluationSubjectNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EvaluationValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    db.commit()
    return service.to_response(row)


@router.get("", response_model=EvaluationListResponse)
async def list_evaluations(
    current_user: CurrentUser,
    subject_type: Literal["lead_analysis", "scout_post"] = Query(...),
    subject_id: int = Query(...),
    db: Session = Depends(get_db),
) -> EvaluationListResponse:
    """All evaluation rows for a subject (newest first) plus the effective map."""
    service = AnalysisEvaluationService(db)
    rows = service.list_for_subject(subject_type, subject_id)
    return EvaluationListResponse(
        subject_type=subject_type,
        subject_id=subject_id,
        evaluations=[service.to_response(r) for r in rows],
        effective=service.effective_map(subject_type, subject_id),
    )


@router.get("/queue", response_model=QueueResponse)
async def get_queue(
    current_user: CurrentUser,
    recommendation: Optional[Literal["suitable", "not_recommended", "needs_review"]] = None,
    dimension_failed: Optional[str] = None,
    watch_id: Optional[int] = None,
    since: Optional[datetime] = None,
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = None,
    sort: Literal["newest", "stratified"] = "newest",
    db: Session = Depends(get_db),
) -> QueueResponse:
    """Unevaluated analysis subjects: recent contradictions first, then newest first."""
    if dimension_failed and dimension_failed not in EVALUABLE_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown dimension: {dimension_failed}",
        )
    service = AnalysisEvaluationService(db)
    return service.queue(
        recommendation=recommendation,
        dimension_failed=dimension_failed,
        watch_id=watch_id,
        since=since,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@router.get("/summary", response_model=EvaluationSummary)
async def get_summary(
    current_user: CurrentUser,
    since: Optional[datetime] = None,
    watch_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> EvaluationSummary:
    """Agreement, tags, confusion matrix, trend, and missing-info aggregates."""
    return AnalysisEvaluationService(db).summary(since=since, watch_id=watch_id)


@router.get("/export")
async def export_dataset(
    current_user: CurrentUser,
    dimension: Optional[str] = Query(
        None, description="Dimension to export; omit for the final verdict"
    ),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream the labelled dataset for one dimension as JSONL (verbatim)."""
    if dimension and dimension not in EVALUABLE_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown dimension: {dimension}",
        )
    service = AnalysisEvaluationService(db)
    # Materialise before streaming so the audit row commits with the request.
    lines = list(service.export_jsonl(dimension))
    db.commit()
    filename = f"evaluations_{dimension or 'final'}.jsonl"
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
