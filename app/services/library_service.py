"""Filesystem-based media library scanning.

v1 treats each top-level entry under the movies/shows roots as one media item.
No metadata provider is consulted yet — that's a future enhancement (Jellyfin
API integration). See the ``NOTE`` markers for extension points.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.library import LibrarySummary, MediaItem, MediaList
from app.services.artwork_service import get_artwork_service
from app.utils.formatting import human_bytes
from app.utils.media_metadata import parse_metadata

logger = get_logger(__name__)


def _entry_size(path: Path, is_dir: bool, max_entries: int = 50_000) -> int:
    if not is_dir:
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                continue
            if count >= max_entries:
                return total
    return total


def _to_item(entry: os.DirEntry[str], with_size: bool, category: str) -> MediaItem:
    path = Path(entry.path)
    is_dir = entry.is_dir()
    try:
        mtime = entry.stat().st_mtime
    except OSError:
        mtime = 0.0
    # Size work stays behind ``with_size`` (the ``sizes=false`` fast path).
    size = _entry_size(path, is_dir) if with_size else 0

    # Cheap, filename-derived metadata (spec §2) — always populated, and the
    # fallback when there's no Jellyfin match below.
    year, quality, hdr = parse_metadata(entry.name)

    # Artwork resolution is O(1) string work backed by caches (spec §4); it is
    # populated even on the fast path since a poster_url string is cheap.
    artwork = get_artwork_service().resolve(str(path), entry.name, year)

    # Movies only: prefer Jellyfin's own title/year over the filename-regex
    # versions when Jellyfin has matched this item — same cached lookup
    # `resolve()` already did above, no extra work. Shows keep the raw
    # folder name for now (out of scope — see CLAUDE.md/plan notes).
    name = entry.name
    if category == "movies":
        if artwork.jellyfin_name:
            name = artwork.jellyfin_name
        if artwork.jellyfin_year is not None:
            year = artwork.jellyfin_year

    return MediaItem(
        name=name,
        path=str(path),
        is_dir=is_dir,
        size_bytes=size,
        size_human=human_bytes(size),
        modified_iso=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        poster_url=artwork.poster_url,
        thumb_url=artwork.thumb_url,
        year=year,
        quality=quality,
        hdr=hdr,
        jellyfin_id=artwork.jellyfin_id,
    )


def _scan(root: Path, media_extensions: set[str]) -> list[os.DirEntry[str]]:
    """Return top-level media entries (dirs, or files with a media extension)."""

    if not root.is_dir():
        return []
    entries: list[os.DirEntry[str]] = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    entries.append(entry)
                elif Path(entry.name).suffix.lower() in media_extensions:
                    entries.append(entry)
    except OSError as exc:  # pragma: no cover - permission/IO issues
        logger.warning("could not scan %s: %s", root, exc)
    return entries


def list_media(
    category: str, settings: Settings | None = None, with_size: bool = True
) -> MediaList:
    """List media items for ``category`` ("movies" or "shows")."""

    settings = settings or get_settings()
    root = settings.movies_path if category == "movies" else settings.shows_path

    entries = _scan(root, settings.media_extensions_set)
    items = [_to_item(e, with_size, category) for e in entries]
    items.sort(key=lambda i: i.name.lower())

    return MediaList(
        category=category,
        root=str(root),
        exists=root.is_dir(),
        count=len(items),
        items=items,
    )


def count_media(category: str, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    root = settings.movies_path if category == "movies" else settings.shows_path
    return len(_scan(root, settings.media_extensions_set))


def get_library_summary(
    settings: Settings | None = None, recent_limit: int = 10
) -> LibrarySummary:
    """High-level library counts plus the most recently modified items."""

    settings = settings or get_settings()

    movie_entries = _scan(settings.movies_path, settings.media_extensions_set)
    show_entries = _scan(settings.shows_path, settings.media_extensions_set)

    # Recently added: sort combined entries by mtime, take newest N. Tag each
    # with its category so `_to_item` can still tell movies from shows after
    # the combined sort. Skip per-item sizing here to keep the summary fast.
    combined: list[tuple[os.DirEntry[str], str]] = [
        (e, "movies") for e in movie_entries
    ] + [(e, "shows") for e in show_entries]

    def _mtime(pair: tuple[os.DirEntry[str], str]) -> float:
        try:
            return pair[0].stat().st_mtime
        except OSError:
            return 0.0

    combined.sort(key=_mtime, reverse=True)
    recent = [
        _to_item(e, with_size=False, category=cat) for e, cat in combined[:recent_limit]
    ]

    return LibrarySummary(
        movies_count=len(movie_entries),
        shows_count=len(show_entries),
        movies_root=str(settings.movies_path),
        shows_root=str(settings.shows_path),
        movies_exists=settings.movies_path.is_dir(),
        shows_exists=settings.shows_path.is_dir(),
        recently_added=recent,
    )
