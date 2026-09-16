"""API routes for agent prompt management.

Endpoints for viewing and editing LLM agent prompts with version control.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rediska_core.api.schemas.agent_prompts import (
    AgentPromptResponse,
    ListAgentPromptsResponse,
    PromptVersionHistoryResponse,
    RollbackPromptRequest,
    UpdateAgentPromptRequest,
)
from rediska_core.api.schemas.evaluations import (
    ReplayCaseResult,
    ReplayCreate,
    ReplayListResponse,
    ReplayResponse,
)
from rediska_core.config import get_settings
from rediska_core.domain.schemas.multi_agent_analysis import AgentPrompt
from rediska_core.domain.services.agent_prompt import AgentPromptService
from rediska_core.domain.services.analysis_evaluation import AnalysisEvaluationService
from rediska_core.domain.services.prompt_replay import ReplayError, create_replay
from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.domain.models import AuditLog, Job, PromptReplay

router = APIRouter(prefix="/agent-prompts", tags=["agent-prompts"])

# List of valid agent dimensions
VALID_DIMENSIONS = [
    "demographics",
    "preferences",
    "relationship_goals",
    "risk_flags",
    "sexual_preferences",
    "meta_analysis",
]


@router.get("", response_model=ListAgentPromptsResponse)
async def list_agent_prompts(
    db: Annotated[Session, Depends(get_db)],
) -> ListAgentPromptsResponse:
    """
    List all agent dimensions with their active prompts.

    Returns all 6 agents with their currently active prompt versions.
    """
    prompt_service = AgentPromptService(db)

    try:
        prompts = prompt_service.get_all_active_prompts()

        # Convert to response schema
        prompts_dict = {}
        for dimension, prompt in prompts.items():
            prompts_dict[dimension] = AgentPromptResponse(
                id=prompt.id,
                agent_dimension=prompt.agent_dimension,
                version=prompt.version,
                system_prompt=prompt.system_prompt,
                output_schema_json=prompt.output_schema_json,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                is_active=prompt.is_active,
                created_at=prompt.created_at.isoformat(),
                created_by=prompt.created_by,
                notes=prompt.notes,
            )

        return ListAgentPromptsResponse(prompts=prompts_dict)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list prompts: {str(e)}",
        )


@router.get("/{dimension}", response_model=AgentPromptResponse)
async def get_agent_prompt(
    dimension: str,
    db: Annotated[Session, Depends(get_db)],
) -> AgentPromptResponse:
    """
    Get the active prompt for a specific dimension.

    Args:
        dimension: Agent dimension (demographics, preferences, etc.)
    """
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )

    prompt_service = AgentPromptService(db)

    try:
        prompt = prompt_service.get_active_prompt(dimension)

        return AgentPromptResponse(
            id=prompt.id,
            agent_dimension=prompt.agent_dimension,
            version=prompt.version,
            system_prompt=prompt.system_prompt,
            output_schema_json=prompt.output_schema_json,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            is_active=prompt.is_active,
            created_at=prompt.created_at.isoformat(),
            created_by=prompt.created_by,
            notes=prompt.notes,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/{dimension}/versions", response_model=PromptVersionHistoryResponse)
async def list_prompt_versions(
    dimension: str,
    db: Annotated[Session, Depends(get_db)],
) -> PromptVersionHistoryResponse:
    """
    List all versions of a prompt for a dimension.

    Args:
        dimension: Agent dimension
    """
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )

    prompt_service = AgentPromptService(db)

    try:
        versions = prompt_service.list_prompt_versions(dimension)
        metrics = AnalysisEvaluationService(db).prompt_version_metrics(dimension)

        versions_response = [
            AgentPromptResponse(
                id=v.id,
                agent_dimension=v.agent_dimension,
                version=v.version,
                system_prompt=v.system_prompt,
                output_schema_json=v.output_schema_json,
                temperature=v.temperature,
                max_tokens=v.max_tokens,
                is_active=v.is_active,
                created_at=v.created_at.isoformat(),
                created_by=v.created_by,
                notes=v.notes,
                evaluations=metrics[v.version].evaluations if v.version in metrics else 0,
                agreement=metrics[v.version].agreement if v.version in metrics else None,
            )
            for v in versions
        ]

        return PromptVersionHistoryResponse(
            dimension=dimension,
            versions=versions_response,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list versions: {str(e)}",
        )


@router.put("/{dimension}", response_model=AgentPromptResponse)
async def update_agent_prompt(
    dimension: str,
    request: UpdateAgentPromptRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AgentPromptResponse:
    """
    Update an agent prompt (creates new version, sets as active).

    Creates a new version of the prompt and immediately activates it.
    The previous version is deactivated.

    Args:
        dimension: Agent dimension
        request: Update request with new prompt values
    """
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )

    prompt_service = AgentPromptService(db)

    try:
        new_prompt = prompt_service.update_prompt(
            dimension=dimension,
            system_prompt=request.system_prompt,
            output_schema_json=request.output_schema_json,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            notes=request.notes,
            created_by="user",
        )

        # Audit log
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="agent_prompt.update",
            entity_type="agent_prompt",
            entity_id=new_prompt.id,
            request_json=request.model_dump(),
            response_json={
                "id": new_prompt.id,
                "version": new_prompt.version,
                "dimension": new_prompt.agent_dimension,
            },
            result="ok",
        )
        db.add(audit_entry)
        db.commit()

        return AgentPromptResponse(
            id=new_prompt.id,
            agent_dimension=new_prompt.agent_dimension,
            version=new_prompt.version,
            system_prompt=new_prompt.system_prompt,
            output_schema_json=new_prompt.output_schema_json,
            temperature=new_prompt.temperature,
            max_tokens=new_prompt.max_tokens,
            is_active=new_prompt.is_active,
            created_at=new_prompt.created_at.isoformat(),
            created_by=new_prompt.created_by,
            notes=new_prompt.notes,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update prompt: {str(e)}",
        )


@router.post("/{dimension}/rollback", response_model=AgentPromptResponse)
async def rollback_agent_prompt(
    dimension: str,
    request: RollbackPromptRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AgentPromptResponse:
    """
    Rollback to a previous prompt version.

    Creates a new version based on the specified previous version
    and activates it.

    Args:
        dimension: Agent dimension
        request: Rollback request with target version
    """
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )

    prompt_service = AgentPromptService(db)

    try:
        rollback_prompt = prompt_service.rollback_to_version(
            dimension=dimension,
            version=request.version,
        )

        # Audit log
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="agent_prompt.rollback",
            entity_type="agent_prompt",
            entity_id=rollback_prompt.id,
            request_json=request.model_dump(),
            response_json={
                "id": rollback_prompt.id,
                "version": rollback_prompt.version,
                "dimension": rollback_prompt.agent_dimension,
            },
            result="ok",
        )
        db.add(audit_entry)
        db.commit()

        return AgentPromptResponse(
            id=rollback_prompt.id,
            agent_dimension=rollback_prompt.agent_dimension,
            version=rollback_prompt.version,
            system_prompt=rollback_prompt.system_prompt,
            output_schema_json=rollback_prompt.output_schema_json,
            temperature=rollback_prompt.temperature,
            max_tokens=rollback_prompt.max_tokens,
            is_active=rollback_prompt.is_active,
            created_at=rollback_prompt.created_at.isoformat(),
            created_by=rollback_prompt.created_by,
            notes=rollback_prompt.notes,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback prompt: {str(e)}",
        )


# =============================================================================
# PROMPT REPLAY (analysis-evaluation)
# =============================================================================


def _replay_response(replay: PromptReplay, include_prompt: bool = False) -> ReplayResponse:
    results = [
        ReplayCaseResult(**{k: v for k, v in r.items() if k in ReplayCaseResult.model_fields})
        for r in (replay.results_json or [])
        if isinstance(r, dict)
    ]
    return ReplayResponse(
        id=replay.id,
        dimension=replay.dimension,
        candidate_version=replay.candidate_version,
        candidate_system_prompt=replay.candidate_system_prompt if include_prompt else None,
        status=replay.status,
        case_count=replay.case_count,
        completed_count=replay.completed_count,
        agreed_count=replay.agreed_count,
        skipped_no_input=replay.skipped_no_input,
        agreement=replay.agreement,
        results=results,
        error=replay.error,
        created_at=replay.created_at,
        started_at=replay.started_at,
        finished_at=replay.finished_at,
    )


def _enqueue_replay(replay_id: int) -> None:
    """Send the replay task to the multi_agent_analysis queue."""
    from celery import Celery

    settings = get_settings()
    celery_app = Celery("rediska_core", broker=settings.celery_broker_url)
    celery_app.send_task(
        "evaluation.replay_prompt",
        args=[replay_id],
        queue="multi_agent_analysis",
    )


@router.post(
    "/{dimension}/replay",
    response_model=ReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_replay(
    dimension: str,
    request: ReplayCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReplayResponse:
    """Replay a draft or existing prompt version against labelled cases.

    Rejected when the dimension has no labelled cases or a replay is already
    running. Never changes the active prompt version.
    """
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )

    settings = get_settings()
    cap = settings.evaluation_replay_max_cases
    max_cases = min(request.max_cases, cap) if request.max_cases else cap

    try:
        replay = create_replay(
            db,
            dimension=dimension,
            system_prompt=request.system_prompt,
            version=request.version,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            max_cases=max_cases,
        )
    except ReplayError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # Job ledger row (idempotency + cancellation), keyed on the replay id.
    job = Job(
        queue_name="multi_agent_analysis",
        job_type="evaluation.replay_prompt",
        payload_json={"replay_id": replay.id, "dimension": dimension},
        dedupe_key=f"evaluation.replay_prompt:{replay.id}",
        status="queued",
        max_attempts=1,
    )
    db.add(job)

    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="prompt.replay",
            entity_type="prompt_replay",
            entity_id=replay.id,
            request_json={
                "dimension": dimension,
                "version": request.version,
                "draft": request.version is None,
                "max_cases": max_cases,
            },
            response_json={"replay_id": replay.id, "case_count": replay.case_count},
            result="ok",
        )
    )
    db.commit()

    try:
        _enqueue_replay(replay.id)
    except Exception as e:  # pragma: no cover - broker down
        replay.status = "failed"
        replay.error = f"Failed to enqueue replay: {e}"
        job.status = "failed"
        job.last_error = replay.error
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=replay.error,
        )

    return _replay_response(replay)


@router.get("/{dimension}/replays", response_model=ReplayListResponse)
async def list_replays(
    dimension: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 20,
) -> ReplayListResponse:
    """Replay history for a dimension, newest first (per-case rows omitted)."""
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dimension: {dimension}",
        )
    rows = (
        db.query(PromptReplay)
        .filter(PromptReplay.dimension == dimension)
        .order_by(PromptReplay.created_at.desc(), PromptReplay.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    replays = []
    for r in rows:
        resp = _replay_response(r)
        resp.results = []
        replays.append(resp)
    return ReplayListResponse(dimension=dimension, replays=replays)


@router.get("/{dimension}/replays/{replay_id}", response_model=ReplayResponse)
async def get_replay(
    dimension: str,
    replay_id: int,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReplayResponse:
    """One replay with status, progress, aggregate, and per-case rows."""
    replay = db.query(PromptReplay).filter(PromptReplay.id == replay_id).first()
    if not replay or replay.dimension != dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Replay not found: {replay_id}",
        )
    return _replay_response(replay, include_prompt=True)


@router.post("/{dimension}/replays/{replay_id}/cancel", response_model=ReplayResponse)
async def cancel_replay(
    dimension: str,
    replay_id: int,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReplayResponse:
    """Cancel a queued or running replay (the worker stops between cases)."""
    replay = db.query(PromptReplay).filter(PromptReplay.id == replay_id).first()
    if not replay or replay.dimension != dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Replay not found: {replay_id}",
        )
    if replay.status in ("queued", "running"):
        replay.status = "cancelled"
        replay.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job = (
            db.query(Job)
            .filter(Job.dedupe_key == f"evaluation.replay_prompt:{replay.id}")
            .first()
        )
        if job and job.status in ("queued", "running"):
            job.status = "cancelled"
        db.add(
            AuditLog(
                ts=datetime.now(timezone.utc),
                actor="user",
                action_type="prompt.replay_cancel",
                entity_type="prompt_replay",
                entity_id=replay.id,
                request_json={"dimension": dimension},
                response_json={"status": replay.status},
                result="ok",
            )
        )
        db.commit()
    return _replay_response(replay)
