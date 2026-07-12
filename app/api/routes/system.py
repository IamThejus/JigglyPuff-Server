"""System health routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.system import SystemOverview
from app.services.system_service import get_system_overview

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/overview", response_model=SystemOverview, summary="CPU / mem / uptime")
async def system_overview() -> SystemOverview:
    return get_system_overview()
