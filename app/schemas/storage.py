"""Response models for storage / disk health."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiskUsage(BaseModel):
    path: str
    exists: bool
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float
    total_human: str
    used_human: str
    free_human: str


class FolderSize(BaseModel):
    path: str
    exists: bool
    size_bytes: int
    size_human: str
    entry_count: int


class SmartHealth(BaseModel):
    available: bool = Field(..., description="Whether SMART data could be read")
    device: str | None = None
    healthy: bool | None = None
    status: str | None = None
    temperature_celsius: int | None = None
    power_on_hours: int | None = None
    message: str | None = None


class StorageSummary(BaseModel):
    disks: list[DiskUsage] = Field(default_factory=list)
    folders: list[FolderSize] = Field(default_factory=list)
    smart: SmartHealth
