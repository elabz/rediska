"""Similarity API routes ("more like this").

Provides:
- POST /similar - nearest indexed documents to a document or to text

Read-only: it ranks what is already stored and writes nothing, so there is no
audit entry. Filters are either applied or refused, never dropped.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.similar import (
    SimilarHit,
    SimilarRequest,
    SimilarResponse,
    SimilarSource,
)
from rediska_core.config import Settings, get_settings
from rediska_core.domain.services.similarity import (
    SimilarityError,
    SimilarityService,
    SourceNotFound,
    UnsupportedFilterError,
)

router = APIRouter(prefix="/similar", tags=["similar"])


def get_similarity_service(
    db: DBSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SimilarityService:
    """Build the similarity service for one request."""
    return SimilarityService(
        db=db,
        es_url=settings.elastic_url,
        embeddings_url=settings.embeddings_url,
        embeddings_model=settings.embeddings_model,
        embeddings_api_key=settings.embeddings_api_key,
    )


SimilarityServiceDep = Annotated[SimilarityService, Depends(get_similarity_service)]


@router.post(
    "",
    response_model=SimilarResponse,
    summary="Find similar content",
    description=(
        "Return the indexed documents nearest to a reference document "
        "(doc_type + entity_id) or to raw text, with what became of each one. "
        "Falls back to text matching when no vector is available, and says so "
        "in `method`."
    ),
)
async def find_similar(
    request: SimilarRequest,
    current_user: CurrentUser,
    service: SimilarityServiceDep,
):
    """Find documents that read like the given document or text."""
    try:
        found = service.find_similar(
            doc_type=request.doc_type,
            entity_id=request.entity_id,
            text=request.text,
            doc_types=request.doc_types,
            author=request.author,
            location=request.location,
            since=request.since,
            until=request.until,
            lead_status=request.lead_status,
            include_deleted=request.include_deleted,
            min_score=request.min_score,
            limit=request.limit,
        )
    except SourceNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "source_not_indexed", "error": str(e)},
        )
    except UnsupportedFilterError as e:
        # A filter that cannot be applied fails the request: answering a
        # narrower question than the one asked would be the silent lie.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unsupported_filter", "error": str(e)},
        )
    except SimilarityError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "similarity_failed", "error": str(e)},
        )

    return SimilarResponse(
        method=found["method"],
        min_score=found["min_score"],
        source=SimilarSource(**found["source"]),
        results=[SimilarHit(**hit) for hit in found["results"]],
    )
