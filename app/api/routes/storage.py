"""Storage / disk health routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.storage import StorageSummary
from app.services.storage_service import get_storage_summary

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/summary", response_model=StorageSummary, summary="Disk usage & SMART")
async def storage_summary(
    folder_sizes: bool = Query(
        default=True,
        description="Include per-folder sizes (slower on large libraries)",
    ),
) -> StorageSummary:
    return get_storage_summary(include_folder_sizes=folder_sizes)
