"""
Movie search and torrent integration.

Provides helpers for searching movies via the YTS search API and
retrieving available torrents for a selected movie.
"""

from __future__ import annotations

from urllib.parse import quote

import requests

from app.core.logging import get_logger

logger = get_logger(__name__)

TMDB_POSTER = "https://image.tmdb.org/t/p/w342"
BASE_URL = "https://en.yts.lu/browse-movies"


def _parse_movies(data: dict) -> list[dict]:
    """Convert the YTS search response into a simplified movie list."""

    results = []

    for movie in data.get("results", []):
        poster = movie.get("poster_path")

        results.append(
            {
                "id": movie.get("id"),
                "title": movie.get("title") or movie.get("original_title"),
                "year": movie.get("release_date", "")[:4],
                "language": movie.get("original_language"),
                "rating": movie.get("vote_average"),
                "overview": movie.get("overview"),
                "thumbnail": (
                    f"{TMDB_POSTER}{poster}" if poster else None
                ),
            }
        )

    return results


def search_movies(query: str, page: int = 1) -> dict:
    """
    Search movies.

    Args:
        query: Movie title.
        page: Search page.

    Returns:
        Search results.
    """

    url = (
        f"{BASE_URL}"
        f"?api=search"
        f"&mode=movie"
        f"&q={quote(query)}"
        f"&page={page}"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        return {
            "success": True,
            "status": response.status_code,
            "results": _parse_movies(response.json()),
        }

    except requests.RequestException as exc:
        logger.exception("Movie search failed")

        return {
            "success": False,
            "status": 500,
            "error": str(exc),
            "results": [],
        }


def get_movie_torrents(
    title: str,
    year: str | None = None,
    quality: str = "all",
) -> dict:
    """
    Get torrent links for a movie.

    Args:
        title: Movie title.
        year: Optional release year.
        quality: Torrent quality.

    Returns:
        Torrent list.
    """

    url = (
        f"{BASE_URL}"
        f"?api=torrents"
        f"&mode=movie"
        f"&name={quote(title)}"
    )

    if year:
        url += f"&year={year}"

    url += f"&quality={quality}"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        return {
            "success": True,
            "status": response.status_code,
            "results": response.json().get("hits", []),
        }

    except requests.RequestException as exc:
        logger.exception("Torrent lookup failed")

        return {
            "success": False,
            "status": 500,
            "error": str(exc),
            "results": [],
        }
