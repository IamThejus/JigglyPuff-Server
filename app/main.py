"""FastAPI application entrypoint.

Run locally with:

    uvicorn app.main:app --reload

On the Dell, this is launched by the systemd unit (see media-server-api.service).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import (
    actions,
    dashboard,
    health,
    library,
    movies,
    services,
    storage,
    system,
    torrents,
    torrents_ws,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.artwork_service import close_artwork_service
from app.services.qbittorrent_service import close_client

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    logger.info("qBittorrent URL: %s", settings.qbittorrent_url)
    logger.info("Media root: %s", settings.media_root)
    if settings.jellyfin_enabled:
        logger.info("Jellyfin artwork source: %s", settings.jellyfin_base_url)
    yield
    # Cleanly close the shared HTTP clients.
    await close_client()
    await close_artwork_service()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Monitoring + limited control API for the Dell home media server. "
            "Serves system, storage, torrent, library and service status to the "
            "mobile dashboard app, plus authenticated torrent-add / sync-movies "
            "control actions and real-time torrent progress over WebSocket."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # v1 API — read-only routes plus authenticated control actions
    # (/actions/*) and the real-time torrents WebSocket.
    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(torrents.router, prefix=api_prefix)
    app.include_router(torrents_ws.router, prefix=api_prefix)
    app.include_router(storage.router, prefix=api_prefix)
    app.include_router(system.router, prefix=api_prefix)
    app.include_router(library.router, prefix=api_prefix)
    app.include_router(services.router, prefix=api_prefix)
    app.include_router(actions.router, prefix=api_prefix)
    app.include_router(movies.router, prefix=api_prefix)

    @app.get("/", tags=["root"], summary="API info")
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{api_prefix}/health",
        }

    return app


app = create_app()
