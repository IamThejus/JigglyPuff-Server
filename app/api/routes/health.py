"""Liveness endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
async def health() -> dict[str, str]:
    """Return a simple OK payload — used for uptime probes and the app splash."""

    return {
        "status": "ok",
        "version": __version__,
        "time": datetime.now(tz=timezone.utc).isoformat(),
    }
