from fastapi import APIRouter

from app.services.movie_fetcher_service import (
    search_movies,
    get_movie_torrents,
)

router = APIRouter(
    prefix="/movies",
    tags=["movies"],
)


@router.get("/search")
async def search(q: str):
    return search_movies(q)


@router.get("/torrents")
async def torrents(title: str, year: str | None = None):
    return get_movie_torrents(title, year)