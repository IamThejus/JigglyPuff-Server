"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate control (``/actions/*``) routes behind a shared API key.

    An unset ``ACTIONS_API_KEY`` is treated as server misconfiguration
    (``503``), not "auth disabled" — a forgotten env var must never leave
    write endpoints open.
    """

    settings = get_settings()
    if not settings.actions_api_key:
        raise HTTPException(
            status_code=503, detail="actions API key not configured on server"
        )
    if x_api_key != settings.actions_api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
