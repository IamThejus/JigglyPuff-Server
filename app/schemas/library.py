"""Response models for the media library."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MediaItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int
    size_human: str
    modified_iso: str

    # --- artwork (spec §1) --------------------------------------------------
    # Relative (starting with "/") or absolute URL the app can GET directly, or
    # ``null`` when no artwork exists (the app then shows its placeholder).
    poster_url: str | None = Field(
        default=None, description="URL for the ~500px poster, or null if unavailable"
    )
    thumb_url: str | None = Field(
        default=None, description="URL for the ~200px thumbnail, or null if unavailable"
    )

    # --- light metadata (spec §1.2 / §2, all optional / nullable) -----------
    year: int | None = Field(default=None, description="Release year, e.g. 2014")
    quality: str | None = Field(
        default=None, description='"2160p" | "1080p" | "720p" | "480p" | null'
    )
    hdr: bool = Field(default=False, description="True if HDR/DV detected")
    jellyfin_id: str | None = Field(
        default=None, description="Jellyfin item id, or null if not sourced from Jellyfin"
    )


class MediaList(BaseModel):
    category: str = Field(..., description="movies | shows")
    root: str
    exists: bool
    count: int
    items: list[MediaItem] = Field(default_factory=list)


class LibrarySummary(BaseModel):
    movies_count: int
    shows_count: int
    movies_root: str
    shows_root: str
    movies_exists: bool
    shows_exists: bool
    recently_added: list[MediaItem] = Field(default_factory=list)
