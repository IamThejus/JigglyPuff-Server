"""Dashboard summary route — the mobile app home screen."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.dashboard import Dashboard
from app.services.dashboard_service import get_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard, summary="Aggregated server summary")
async def dashboard() -> Dashboard:
    return await get_dashboard()
