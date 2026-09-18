"""Contact ban list API routes.

Provides endpoints for:
- GET  /ban-list - List entries (status/source/q filters, keyset cursor)
- GET  /ban-list/status - Ban state of one username
- GET  /ban-list/suggestions - Copy-ring authors to consider (never auto-banned)
- POST /ban-list/suggestions/dismiss - Dismiss one author's suggestion
- POST /ban-list/bulk - Ban a cluster's authors (minus exclusions) as one batch
- POST /ban-list - Ban one username (create or reactivate)
- POST /ban-list/{id}/lift - Lift a ban, restoring withdrawn leads

Static paths are declared before ``/{ban_id}``. Every mutation writes
``audit_log`` (in ``BanListService``). Nothing is banned without a user action.
"""

from typing import NoReturn, Optional

from fastapi import APIRouter, HTTPException, Query, status

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.ban_list import (
    BanBulkRequest,
    BanBulkResponse,
    BanCreateRequest,
    BanCreateResponse,
    BanEntryResponse,
    BanLiftRequest,
    BanLiftResponse,
    BanListResponse,
    BanStatusResponse,
    BanSuggestionsResponse,
    DismissSuggestionRequest,
)
from rediska_core.domain.models import DoNotContact
from rediska_core.domain.services.ban_list import (
    BAN_SOURCES,
    BAN_STATUSES,
    SOURCE_COPY_RING,
    SOURCE_MANUAL,
    STATUS_ACTIVE,
    BanListError,
    BanListService,
    BanNotFoundError,
    BanResult,
    copy_tables_present,
    normalize_username,
)

router = APIRouter(prefix="/ban-list", tags=["ban-list"])


def _raise_http(exc: BanListError) -> NoReturn:
    if isinstance(exc, BanNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _entry_responses(service: BanListService, entries: list[DoNotContact]) -> list[BanEntryResponse]:
    """Build responses with account + lead links in two batched queries."""
    accounts = service.accounts_for(entries)
    leads = service.lead_ids_for(a.id for a in accounts.values())
    out = []
    for e in entries:
        account = accounts.get((e.provider_id, e.external_username.lower()))
        out.append(
            BanEntryResponse(
                id=e.id,
                provider_id=e.provider_id,
                username=e.external_username,
                reason=e.reason,
                notes=e.notes,
                source=e.source,
                status=e.status,
                cluster_id=e.cluster_id,
                created_by=e.created_by,
                created_at=e.created_at,
                lifted_at=e.lifted_at,
                account_id=account.id if account else None,
                lead_ids=leads.get(account.id, []) if account else [],
            )
        )
    return out


def _create_response(service: BanListService, result: BanResult) -> BanCreateResponse:
    return BanCreateResponse(
        entry=_entry_responses(service, [result.entry])[0],
        created=result.created,
        reactivated=result.reactivated,
        leads_withdrawn=result.leads_withdrawn,
    )


@router.get("", response_model=BanListResponse, summary="List ban entries")
async def list_bans(
    current_user: CurrentUser,
    db: DBSession,
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search username, reason, notes"),
    provider_id: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    if status_filter and status_filter not in BAN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    if source and source not in BAN_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
    try:
        cursor_id = int(cursor) if cursor else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {cursor}")

    service = BanListService(db)
    entries, next_id = service.list_entries(
        provider_id=provider_id,
        status=status_filter,
        source=source,
        q=q,
        cursor=cursor_id,
        limit=limit,
    )
    return BanListResponse(
        items=_entry_responses(service, entries),
        next_cursor=str(next_id) if next_id else None,
    )


@router.get("/status", response_model=BanStatusResponse, summary="Ban state of a username")
async def ban_status(
    current_user: CurrentUser,
    db: DBSession,
    username: str = Query(..., min_length=1),
    provider_id: str = Query("reddit"),
):
    name = normalize_username(username)
    entry = (
        db.query(DoNotContact)
        .filter(DoNotContact.provider_id == provider_id, DoNotContact.external_username == name)
        .first()
    )
    if entry is None:
        return BanStatusResponse(banned=False, entry=None)
    service = BanListService(db)
    return BanStatusResponse(
        banned=entry.status == STATUS_ACTIVE,
        entry=_entry_responses(service, [entry])[0],
    )


@router.get(
    "/suggestions",
    response_model=BanSuggestionsResponse,
    summary="Copy-ring authors suggested for a ban",
)
async def list_suggestions(
    current_user: CurrentUser,
    db: DBSession,
    provider_id: str = Query("reddit"),
):
    if not copy_tables_present(db):
        return BanSuggestionsResponse(available=False, items=[])
    return BanSuggestionsResponse(
        available=True,
        items=BanListService(db).suggestions(provider_id),  # type: ignore[arg-type]
    )


@router.post("/suggestions/dismiss", summary="Dismiss one author's ban suggestion")
async def dismiss_suggestion(
    request: DismissSuggestionRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    try:
        touched = BanListService(db).dismiss_suggestion(request.cluster_id, request.username)
    except BanListError as e:
        _raise_http(e)
    db.commit()
    return {"cluster_id": request.cluster_id, "username": request.username, "members": touched}


@router.post("/bulk", response_model=BanBulkResponse, summary="Ban a cluster's authors")
async def bulk_ban(
    request: BanBulkRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    service = BanListService(db)
    usernames = request.usernames
    if not usernames:
        if request.cluster_id is None:
            raise HTTPException(status_code=400, detail="Provide cluster_id or usernames")
        usernames = service.cluster_usernames(request.cluster_id, request.provider_id)
        if not usernames:
            raise HTTPException(
                status_code=404, detail=f"Copy cluster {request.cluster_id} has no authors"
            )
    try:
        results = service.bulk_ban(
            request.provider_id,
            usernames,
            request.reason,
            cluster_id=request.cluster_id,
            exclude_usernames=request.exclude_usernames,
            notes=request.notes,
            source=SOURCE_COPY_RING if request.cluster_id is not None else SOURCE_MANUAL,
        )
    except BanListError as e:
        _raise_http(e)
    db.commit()
    return BanBulkResponse(
        cluster_id=request.cluster_id,
        banned=[_create_response(service, r) for r in results],
    )


@router.post(
    "",
    response_model=BanCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ban a username",
)
async def create_ban(
    request: BanCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    service = BanListService(db)
    try:
        result = service.ban(
            request.provider_id,
            request.username,
            request.reason,
            notes=request.notes,
            source=SOURCE_MANUAL,
        )
    except BanListError as e:
        _raise_http(e)
    db.commit()
    return _create_response(service, result)


@router.post("/{ban_id}/lift", response_model=BanLiftResponse, summary="Lift a ban")
async def lift_ban(
    ban_id: int,
    current_user: CurrentUser,
    db: DBSession,
    request: Optional[BanLiftRequest] = None,
):
    service = BanListService(db)
    try:
        entry, restored = service.lift(ban_id, notes=request.notes if request else None)
    except BanListError as e:
        _raise_http(e)
    db.commit()
    return BanLiftResponse(entry=_entry_responses(service, [entry])[0], leads_restored=restored)
