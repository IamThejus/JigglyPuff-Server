"""Request/response models for control actions (/api/v1/actions/*)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddTorrentUrlRequest(BaseModel):
    url: str
    category: str | None = None
    save_path: str | None = None
    paused: bool = False


class AddTorrentResponse(BaseModel):
    ok: bool
    message: str | None = None


class TorrentActionRequest(BaseModel):
    """Target a single torrent by its info hash (pause/resume/delete)."""

    hash: str


class TorrentActionResponse(BaseModel):
    ok: bool
    message: str | None = None


class SyncMoviesResponse(BaseModel):
    ok: bool
    exit_code: int
    output: str
    message: str | None = None
    # Items the script moved into the library this run (basenames).
    moved: list[str] = Field(default_factory=list)
    # Items skipped because they already existed in the library (basenames).
    skipped: list[str] = Field(default_factory=list)
    # How many qBittorrent entries were removed for the moved items
    # (metadata only — the moved files are preserved).
    torrents_removed: int = 0
