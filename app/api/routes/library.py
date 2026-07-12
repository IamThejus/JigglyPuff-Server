"""Media library routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.schemas.library import LibrarySummary, MediaList
from app.services.artwork_service import get_artwork_service
from app.services.library_service import get_library_summary, list_media

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/summary", response_model=LibrarySummary, summary="Library counts")
async def library_summary() -> LibrarySummary:
    await get_artwork_service().ensure_jellyfin_map()
    return get_library_summary()


@router.get("/movies", response_model=MediaList, summary="List movies")
async def movies(
    sizes: bool = Query(default=True, description="Compute per-item folder sizes"),
) -> MediaList:
    await get_artwork_service().ensure_jellyfin_map()
    return list_media("movies", with_size=sizes)


@router.get("/shows", response_model=MediaList, summary="List shows")
async def shows(
    sizes: bool = Query(default=True, description="Compute per-item folder sizes"),
) -> MediaList:
    await get_artwork_service().ensure_jellyfin_map()
    return list_media("shows", with_size=sizes)


@router.get(
    "/artwork",
    summary="Poster / thumbnail image bytes",
    responses={
        200: {"content": {"image/*": {}}, "description": "Downscaled artwork bytes"},
        304: {"description": "Not modified (ETag matched)"},
        404: {"description": "No artwork available for this item"},
    },
)
async def artwork(
    request: Request,
    path: str | None = Query(
        default=None, description="URL-encoded library item path (Option B)"
    ),
    id: str | None = Query(
        default=None, description="Jellyfin item id (Option A)"
    ),
    size: str = Query(default="poster", description="poster (~500px) | thumb (~200px)"),
) -> Response:
    """Proxy/stream a downscaled poster or thumbnail.

    Returns ``404`` (never ``500``) when the art is missing — image loads are
    the one place the app falls back to its placeholder gracefully (spec §1.3).
    """

    if path is None and id is None:
        return Response(status_code=404)

    result = await get_artwork_service().fetch(id=id, path=path, size=size)
    if result is None:
        return Response(status_code=404)

    # Poster art almost never changes: cache aggressively and honour revalidation.
    cache_headers = {
        "Cache-Control": "public, max-age=86400",
        "ETag": result.etag,
    }

    if request.headers.get("if-none-match") == result.etag:
        return Response(status_code=304, headers=cache_headers)

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers=cache_headers,
    )
