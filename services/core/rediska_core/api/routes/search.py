"""Search API routes.

Provides endpoints for:
- POST /search - Hybrid search across indexed content
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rediska_core.api.deps import CurrentUser
from rediska_core.api.schemas.search import (
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from rediska_core.config import Settings, get_settings
from rediska_core.domain.services.search import (
    SearchError,
    SearchService,
    MAX_LIMIT,
)

router = APIRouter(prefix="/search", tags=["search"])


def get_search_service(settings: Annotated[Settings, Depends(get_settings)]) -> SearchService:
    """Get the search service."""
    return SearchService(
        es_url=settings.elastic_url,
        embeddings_url=settings.embeddings_url,
        embeddings_model=settings.embeddings_model,
        embeddings_api_key=settings.embeddings_api_key,
    )


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search content",
    description="Search across indexed content using hybrid search (BM25 + kNN). "
                "Supports filtering by provider, identity, document type, and visibility.",
)
async def search(
    request: SearchRequest,
    current_user: CurrentUser,
    search_service: SearchServiceDep,
):
    """Perform search across indexed content.

    Uses hybrid search (combining BM25 text matching with kNN vector similarity)
    by default. Can be switched to text-only or vector-only mode.

    Filters:
    - provider_id: Filter by provider (e.g., 'reddit')
    - identity_id: Filter by identity
    - doc_types: Filter by document types
    - exclude_visibility: Exclude certain visibility states

    Pagination:
    - offset: Skip first N results
    - limit: Maximum results (capped at 100)
    """
    try:
        # Enforce max limit
        limit = min(request.limit, MAX_LIMIT)

        # Common kwargs for all search methods
        search_kwargs = {
            "query": request.query,
            "provider_id": request.provider_id,
            "identity_id": request.identity_id,
            "doc_types": request.doc_types,
            "exclude_visibility": request.exclude_visibility,
            "include_deleted": request.include_deleted,
        }

        if request.mode == "text":
            result = search_service.text_search(
                **search_kwargs,
                offset=request.offset,
                limit=limit,
            )
        elif request.mode == "vector":
            result = search_service.vector_search(
                **search_kwargs,
                k=limit,
            )
        else:  # hybrid (default)
            result = search_service.hybrid_search(
                **search_kwargs,
                offset=request.offset,
                limit=limit,
            )

        # Format response
        hits = [
            SearchHit(
                id=hit["id"],
                score=hit.get("score", 0.0),
                source=hit.get("source", {}),
            )
            for hit in result.get("hits", [])
        ]

        return SearchResponse(
            total=result.get("total", 0),
            hits=hits,
            max_score=result.get("max_score"),
        )

    except SearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": f"Search failed: {e}"},
        )
