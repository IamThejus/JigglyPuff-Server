"""Response models for qBittorrent torrent status."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Torrent(BaseModel):
    hash: str
    name: str
    state: str
    category: str | None = None
    progress: float = Field(..., description="0.0 - 1.0")
    progress_percent: float = Field(..., description="0 - 100")
    size_bytes: int
    size_human: str
    downloaded_bytes: int
    dlspeed_bytes: int
    upspeed_bytes: int
    dlspeed_human: str
    upspeed_human: str
    eta_seconds: int | None = None
    eta_human: str | None = None
    ratio: float
    num_seeds: int
    num_leechs: int
    added_on_iso: str | None = None


class TorrentsSummary(BaseModel):
    reachable: bool = Field(..., description="Whether qBittorrent responded")
    total: int = 0
    downloading: int = 0
    seeding: int = 0
    completed: int = 0
    paused: int = 0
    error: int = 0
    total_dlspeed_bytes: int = 0
    total_upspeed_bytes: int = 0
    total_dlspeed_human: str = "0 B"
    total_upspeed_human: str = "0 B"
    # Client identity (spec §3.1). All null when unknown / unreachable.
    client_name: str | None = Field(default=None, description="e.g. qBittorrent")
    client_version: str | None = Field(default=None, description="e.g. 4.5.2")
    node: str | None = Field(default=None, description="Node label, if applicable")
    message: str | None = None


class TorrentsList(BaseModel):
    reachable: bool
    count: int
    torrents: list[Torrent] = Field(default_factory=list)
    message: str | None = None
