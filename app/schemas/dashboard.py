"""Response model for the aggregated dashboard summary."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.services import ServiceStatus


class DashboardStorage(BaseModel):
    primary_path: str
    total_human: str
    used_human: str
    free_human: str
    percent_used: float


class Dashboard(BaseModel):
    hostname: str
    server_name: str
    uptime_seconds: int
    uptime_human: str

    cpu_percent: float
    memory_percent: float
    disk_percent_used: float

    storage: DashboardStorage

    torrents_active: int
    torrents_downloading: int
    torrents_seeding: int
    torrents_reachable: bool

    movies_count: int
    shows_count: int

    services: list[ServiceStatus] = Field(default_factory=list)
    generated_at_iso: str
