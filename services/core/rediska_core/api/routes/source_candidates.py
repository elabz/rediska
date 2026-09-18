"""Source discovery API routes.

Provides endpoints for:
- GET  /source-candidates - List candidates (kind/status filters, lift sort, cursor)
- POST /source-candidates - Add a searched location as a manual candidate
- GET  /source-candidates/search - Provider location search, annotated
- POST /source-candidates/trials/{trial_id}/cancel - Cancel a trial
- GET  /source-candidates/{id} - One candidate
- POST /source-candidates/{id}/dismiss | restore | snooze | accept | trial

Static paths are declared before ``/{candidate_id}``. Every mutation writes
``audit_log``. Nothing here creates or activates a watch without an explicit
accept, and nothing fetches an unregistered external host.
"""

import logging
from datetime import datetime, timezone
from typing import Any, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.source_discovery import (
    AcceptRequest,
    AcceptResponse,
    LocationInfo,
    LocationSearchResponse,
    LocationSearchResult,
    ManualCandidateRequest,
    SnoozeRequest,
    SourceCandidateListResponse,
    SourceCandidateResponse,
    SourceTrialResponse,
    TrialRequest,
    TrialYield,
)
from rediska_core.config import get_settings
from rediska_core.domain.models import AuditLog, SourceCandidate, SourceTrial
from rediska_core.domain.services.source_discovery import (
    CANDIDATE_STATUSES,
    KIND_EXTERNAL_HOST,
    KIND_LOCATION,
    DiscoveryConflictError,
    DiscoveryError,
    DiscoveryNotFoundError,
    SourceDiscoveryService,
)

router = APIRouter(prefix="/source-candidates", tags=["source-discovery"])
logger = logging.getLogger(__name__)

# Lazy location-info lookups per list request, so a first view of a long list
# does not spend the shared Reddit budget in one burst.
MAX_INFO_FETCHES_PER_REQUEST = 10


# =============================================================================
# HELPERS
# =============================================================================


def _audit(
    db: Session,
    action_type: str,
    entity_id: Optional[int],
    request_json: Optional[dict] = None,
    response_json: Optional[dict] = None,
    entity_type: str = "source_candidate",
) -> None:
    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            request_json=request_json,
            response_json=response_json,
            result="ok",
        )
    )


def _raise_http(exc: DiscoveryError) -> NoReturn:
    if isinstance(exc, DiscoveryNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, DiscoveryConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _location_dict(location: Any) -> dict[str, Any]:
    return {
        "name": location.name,
        "title": location.title,
        "description": location.description,
        "member_count": location.member_count,
        "active_count": location.active_count,
        "is_nsfw": bool(location.is_nsfw),
        "created_at": location.created_at.isoformat() if location.created_at else None,
        "rules": list(getattr(location, "rules", None) or []),
    }


def _trial_response(trial: Optional[SourceTrial]) -> Optional[SourceTrialResponse]:
    if trial is None:
        return None
    return SourceTrialResponse(
        id=trial.id,
        candidate_id=trial.candidate_id,
        watch_id=trial.watch_id,
        run_id=trial.run_id,
        status=trial.status,
        sample_size=trial.sample_size,
        posts_total=trial.posts_total,
        progress=trial.progress,
        yield_report=TrialYield(**trial.yield_json) if trial.yield_json else None,
        error=trial.error,
        created_at=trial.created_at,
        started_at=trial.started_at,
        finished_at=trial.finished_at,
    )


def _candidate_response(
    candidate: SourceCandidate, latest_trial: Optional[SourceTrial] = None
) -> SourceCandidateResponse:
    info = candidate.location_info_json if isinstance(candidate.location_info_json, dict) else None
    unavailable = bool(info and info.get("unavailable"))
    contact_rule = info.get("contact_rule") if info else None
    return SourceCandidateResponse(
        id=candidate.id,
        provider_id=candidate.provider_id,
        kind=candidate.kind,
        name=candidate.name,
        origin=candidate.origin,
        status=candidate.status,
        lift=candidate.lift,
        evidence_count=candidate.evidence_count,
        evidence=candidate.evidence_json or {},
        snoozed_until=candidate.snoozed_until,
        location_info=LocationInfo(**info) if info and not unavailable else None,
        location_unavailable=unavailable,
        contact_restricted=bool(contact_rule),
        contact_rule=contact_rule,
        watch_id=candidate.watch_id,
        latest_trial=_trial_response(latest_trial),
        computed_at=candidate.computed_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


async def _fill_location_info(
    db: Session, service: SourceDiscoveryService, candidates: list[SourceCandidate]
) -> None:
    """Fetch and cache location info for candidates displayed without it.

    Best effort: no identity, a provider error, or an unsupported provider
    leaves the info empty and the list still renders.
    """
    pending = [c for c in candidates if service.needs_location_info(c)]
    if not pending:
        return
    from rediska_core.providers.reddit.factory import (
        AdapterUnavailableError,
        adapter_for_identity,
    )

    try:
        adapter = adapter_for_identity(db)
    except AdapterUnavailableError as exc:
        logger.info(f"Skipping location info lookups: {exc}")
        return

    try:
        for candidate in pending[:MAX_INFO_FETCHES_PER_REQUEST]:
            try:
                location = await adapter.get_location_info(candidate.name)
            except NotImplementedError:
                return
            except Exception as exc:
                logger.warning(f"Location info lookup failed for {candidate.name}: {exc}")
                continue
            service.store_location_info(
                candidate, _location_dict(location) if location is not None else None
            )
        db.commit()
    finally:
        await adapter.aclose()


def _enqueue_trial(trial_id: int) -> None:
    """Send the trial task to the scout queue."""
    from celery import Celery

    settings = get_settings()
    celery_app = Celery("rediska_core", broker=settings.celery_broker_url)
    celery_app.send_task(
        "discovery.run_trial", kwargs={"trial_id": trial_id}, queue="scout"
    )


def _parse_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cursor: {cursor}"
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cursor: {cursor}"
        )
    return offset


# =============================================================================
# LIST / CREATE
# =============================================================================


@router.get("", response_model=SourceCandidateListResponse)
async def list_candidates(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    kind: Optional[str] = Query(None, description="location | external_host"),
    candidate_status: Optional[str] = Query(
        None,
        alias="status",
        description="new | trialled | accepted | dismissed | snoozed | all "
        "(default: new, trialled, and snoozes that have passed)",
    ),
    cursor: Optional[str] = Query(None, description="Cursor from a previous page"),
    limit: int = Query(25, ge=1, le=100),
    hide_restricted: bool = Query(
        False, description="Hide locations whose rules forbid contacting posters"
    ),
    q: Optional[str] = Query(None, max_length=100, description="Name contains (e.g. 'r4r')"),
) -> SourceCandidateListResponse:
    """Candidates sorted by lift descending (external hosts after locations)."""
    if kind is not None and kind not in (KIND_LOCATION, KIND_EXTERNAL_HOST):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid kind: {kind}")
    if candidate_status is not None and candidate_status not in (*CANDIDATE_STATUSES, "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {candidate_status}"
        )
    offset = _parse_cursor(cursor)

    service = SourceDiscoveryService(db)
    candidates, total = service.list_candidates(
        kind=kind,
        status=candidate_status,
        offset=offset,
        limit=limit,
        hide_restricted=hide_restricted,
        name_contains=q,
    )
    await _fill_location_info(db, service, candidates)
    # Lookups made just now can reveal a location as gone or rule-restricted;
    # drop those from this page too so the filters hold on first display.
    if candidate_status != "all":
        shown = [
            c for c in candidates
            if not (c.location_info_json or {}).get("unavailable")
            and not (hide_restricted and (c.location_info_json or {}).get("contact_rule"))
        ]
        total -= len(candidates) - len(shown)
        candidates = shown

    trials = service.latest_trials(c.id for c in candidates)
    next_offset = offset + len(candidates)
    return SourceCandidateListResponse(
        items=[_candidate_response(c, trials.get(c.id)) for c in candidates],
        total=total,
        next_cursor=str(next_offset) if next_offset < total else None,
        running_trial=_trial_response(service.running_trial()),
    )


@router.post("", response_model=SourceCandidateResponse, status_code=status.HTTP_201_CREATED)
async def add_manual_candidate(
    request: ManualCandidateRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceCandidateResponse:
    """Add a location (usually from search) as a `manual` candidate."""
    service = SourceDiscoveryService(db)
    info = request.location_info.model_dump(mode="json") if request.location_info else None
    try:
        candidate = service.add_manual(request.name, location_info=info)
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(db, "source_candidate.add_manual", candidate.id, request_json={"name": request.name})
    db.commit()
    return _candidate_response(candidate)


# =============================================================================
# SEARCH (static path, before /{candidate_id})
# =============================================================================


@router.get("/search", response_model=LocationSearchResponse)
async def search_locations(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(25, ge=1, le=100),
    identity_id: Optional[int] = Query(None, description="Identity to search with"),
) -> LocationSearchResponse:
    """Provider location search, annotated with watched/candidate status.

    Results are not filtered by NSFW status.
    """
    from rediska_core.providers.reddit.factory import (
        AdapterUnavailableError,
        adapter_for_identity,
    )

    try:
        adapter = adapter_for_identity(db, identity_id)
    except AdapterUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        locations = await adapter.search_locations(q, limit=limit)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.warning(f"Location search failed for {q!r}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Location search failed: {exc}"
        )
    finally:
        await adapter.aclose()

    annotations = SourceDiscoveryService(db).annotate_locations(l.name for l in locations)
    return LocationSearchResponse(
        query=q,
        results=[
            LocationSearchResult(**_location_dict(l), **annotations.get(l.name, {}))
            for l in locations
        ],
    )


@router.post("/trials/{trial_id}/cancel", response_model=SourceTrialResponse)
async def cancel_trial(
    trial_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceTrialResponse:
    """Cancel a queued or running trial (the worker stops between posts)."""
    service = SourceDiscoveryService(db)
    try:
        trial = service.cancel_trial(service.get_trial(trial_id))
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(
        db,
        "source_trial.cancel",
        trial.id,
        request_json={"candidate_id": trial.candidate_id},
        response_json={"status": trial.status},
        entity_type="source_trial",
    )
    db.commit()
    return _trial_response(trial)  # type: ignore[return-value]


# =============================================================================
# SINGLE CANDIDATE
# =============================================================================


@router.get("/{candidate_id}", response_model=SourceCandidateResponse)
async def get_candidate(
    candidate_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceCandidateResponse:
    service = SourceDiscoveryService(db)
    try:
        candidate = service.get(candidate_id)
    except DiscoveryError as exc:
        _raise_http(exc)
    await _fill_location_info(db, service, [candidate])
    return _candidate_response(candidate, service.latest_trials([candidate.id]).get(candidate.id))


@router.post("/{candidate_id}/dismiss", response_model=SourceCandidateResponse)
async def dismiss_candidate(
    candidate_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceCandidateResponse:
    """Dismiss permanently (until restored); re-mining never resurrects it."""
    service = SourceDiscoveryService(db)
    try:
        candidate = service.dismiss(service.get(candidate_id))
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(db, "source_candidate.dismiss", candidate.id, request_json={"name": candidate.name})
    db.commit()
    return _candidate_response(candidate, service.latest_trials([candidate.id]).get(candidate.id))


@router.post("/{candidate_id}/restore", response_model=SourceCandidateResponse)
async def restore_candidate(
    candidate_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceCandidateResponse:
    service = SourceDiscoveryService(db)
    try:
        candidate = service.restore(service.get(candidate_id))
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(
        db,
        "source_candidate.restore",
        candidate.id,
        request_json={"name": candidate.name},
        response_json={"status": candidate.status},
    )
    db.commit()
    return _candidate_response(candidate, service.latest_trials([candidate.id]).get(candidate.id))


@router.post("/{candidate_id}/snooze", response_model=SourceCandidateResponse)
async def snooze_candidate(
    candidate_id: int,
    request: SnoozeRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SourceCandidateResponse:
    service = SourceDiscoveryService(db)
    try:
        candidate = service.snooze(service.get(candidate_id), request.until)
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(
        db,
        "source_candidate.snooze",
        candidate.id,
        request_json={"name": candidate.name, "until": request.until.isoformat()},
    )
    db.commit()
    return _candidate_response(candidate, service.latest_trials([candidate.id]).get(candidate.id))


@router.post("/{candidate_id}/accept", response_model=AcceptResponse)
async def accept_candidate(
    candidate_id: int,
    request: AcceptRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> AcceptResponse:
    """Create a scout watch from the candidate with the user's settings.

    A candidate that was trialled has its hidden trial watch converted in
    place, so the posts the trial already analysed are not analysed again.
    """
    service = SourceDiscoveryService(db)
    try:
        candidate = service.get(candidate_id)
        existing_watch = service.candidate_watch(candidate)
        had_trial_watch = bool(existing_watch is not None and existing_watch.is_trial)
        watch = service.accept(candidate, **request.model_dump())
    except DiscoveryError as exc:
        _raise_http(exc)
    except Exception as exc:
        # ScoutWatchError from watch validation (e.g. unknown identity)
        from rediska_core.domain.services.scout_watch import ScoutWatchError

        if isinstance(exc, ScoutWatchError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        raise

    _audit(
        db,
        "source_candidate.accept",
        candidate.id,
        request_json={"name": candidate.name, **request.model_dump()},
        response_json={"watch_id": watch.id, "converted_trial_watch": had_trial_watch},
    )
    db.commit()
    return AcceptResponse(
        candidate=_candidate_response(
            candidate, service.latest_trials([candidate.id]).get(candidate.id)
        ),
        watch_id=watch.id,
        converted_trial_watch=had_trial_watch,
    )


@router.post(
    "/{candidate_id}/trial",
    response_model=SourceTrialResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_trial(
    candidate_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    request: Optional[TrialRequest] = None,
) -> SourceTrialResponse:
    """Enqueue a bounded trial of a location candidate (one trial at a time)."""
    options = request or TrialRequest()
    service = SourceDiscoveryService(db)
    try:
        trial = service.start_trial(
            service.get(candidate_id),
            sample_size=options.sample_size,
            identity_id=options.identity_id,
        )
    except DiscoveryError as exc:
        _raise_http(exc)
    _audit(
        db,
        "source_trial.start",
        trial.id,
        request_json={"candidate_id": candidate_id, "sample_size": trial.sample_size},
        response_json={"watch_id": trial.watch_id, "job_id": trial.job_id},
        entity_type="source_trial",
    )
    db.commit()

    try:
        _enqueue_trial(trial.id)
    except Exception as exc:
        logger.exception(f"Failed to enqueue trial {trial.id}: {exc}")
        trial.status = "failed"
        trial.error = f"Failed to enqueue: {exc}"[:2000]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue trial: {exc}",
        )
    return _trial_response(trial)  # type: ignore[return-value]
