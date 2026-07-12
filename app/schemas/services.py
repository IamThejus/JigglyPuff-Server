"""Response models for systemd service status."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str
    active: bool = Field(..., description="True when the unit is active/running")
    state: str = Field(..., description="e.g. active, inactive, failed, unknown")
    sub_state: str | None = Field(
        default=None, description="e.g. running, dead, exited"
    )
    enabled: bool | None = Field(
        default=None, description="Whether the unit is enabled at boot"
    )


class ServicesResponse(BaseModel):
    available: bool = Field(..., description="Whether systemctl could be queried")
    services: list[ServiceStatus] = Field(default_factory=list)
    message: str | None = None
