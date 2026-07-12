"""systemd service status routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.services import ServicesResponse
from app.services.service_status_service import get_services_status

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=ServicesResponse, summary="Status of key services")
async def services() -> ServicesResponse:
    return get_services_status()
