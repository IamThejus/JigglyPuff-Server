"""Application configuration.

All runtime configuration is loaded from environment variables (or a local
``.env`` file). See ``.env.example`` for the full list of supported settings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from the process environment first and fall back to the
    ``.env`` file in the project root. This keeps machine-specific values (the
    Dell's paths, qBittorrent credentials, etc.) out of the codebase.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # API / server
    # ------------------------------------------------------------------ #
    app_name: str = "Media Server API"
    app_env: str = Field(default="development", description="development | production")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Comma-separated list of allowed CORS origins. Use "*" to allow all
    # (fine for a LAN-only home server; tighten for remote access).
    allowed_origins: str = "*"

    # ------------------------------------------------------------------ #
    # qBittorrent Web API
    # ------------------------------------------------------------------ #
    qbittorrent_url: str = "http://127.0.0.1:8080"
    qbittorrent_username: str = "admin"
    qbittorrent_password: str = "adminadmin"
    qbittorrent_timeout: float = 10.0

    # ------------------------------------------------------------------ #
    # Control actions (/api/v1/actions/*, /api/v1/torrents/ws)
    # ------------------------------------------------------------------ #
    # Shared secret required as the X-API-Key header on every /actions/*
    # route. Left empty by default so control endpoints fail closed (503)
    # rather than silently opening up if this is forgotten.
    actions_api_key: str = ""

    # sync-movies is an existing shell script on the Dell (moves completed
    # downloads into the movies library) — the API shells out to it rather
    # than reimplementing its logic.
    sync_movies_script_path: str = "/usr/local/bin/sync-movies"
    sync_movies_timeout: float = 120.0

    # Max accepted size for an uploaded .torrent file.
    torrent_file_max_mb: int = 10

    # Seconds between torrent-list pushes on the /torrents/ws WebSocket.
    torrents_ws_interval: float = 2.0

    # ------------------------------------------------------------------ #
    # Storage layout on the Dell
    # ------------------------------------------------------------------ #
    media_root: Path = Path("/srv/storage/media")
    movies_path: Path = Path("/srv/storage/media/movies")
    shows_path: Path = Path("/srv/storage/media/shows")
    downloads_root: Path = Path("/srv/storage/downloads")
    torrents_complete_path: Path = Path("/srv/storage/downloads/torrents/complete")
    torrents_incomplete_path: Path = Path("/srv/storage/downloads/torrents/incomplete")

    # Paths whose disk usage / free space we report in the storage summary.
    # Comma-separated absolute paths.
    monitored_paths: str = "/srv/storage,/srv/storage/media,/srv/storage/downloads"

    # Block device to query for SMART health (e.g. /dev/sda). Leave empty to
    # skip SMART checks.
    smart_device: str = ""

    # ------------------------------------------------------------------ #
    # Services to report on (systemd unit names)
    # ------------------------------------------------------------------ #
    # Comma-separated systemd unit names.
    monitored_services: str = "jellyfin,qbittorrent-nox,smbd,ssh"

    # Recognised media file extensions used when scanning the library.
    media_extensions: str = ".mkv,.mp4,.avi,.mov,.m4v,.wmv,.flv,.webm,.ts,.m2ts"

    # ------------------------------------------------------------------ #
    # Library artwork (posters / thumbnails)
    # ------------------------------------------------------------------ #
    # Jellyfin is the preferred artwork source (Option A in the spec): the
    # backend proxies posters Jellyfin already scraped. Leave either value
    # empty to disable Jellyfin — the API then falls back to local artwork
    # files next to each title (Option B) and, failing that, ``poster_url:
    # null``. Artwork problems must never surface as an error to the app.
    jellyfin_base_url: str = ""
    jellyfin_api_key: str = ""
    # How long (seconds) to cache the folder→Jellyfin item mapping. The list
    # path only ever reads this cache; it never hits Jellyfin per request.
    jellyfin_map_ttl: float = 300.0

    # Local artwork filenames looked up next to each title (Option B),
    # checked in order. Comma-separated.
    artwork_filenames: str = (
        "poster.jpg,poster.png,poster.webp,folder.jpg,folder.png,cover.jpg,cover.png"
    )
    # Cache TTL (seconds) for the per-folder local-artwork existence check so
    # the list path stays cheap (see spec §4 Performance).
    artwork_local_ttl: float = 300.0

    # Target heights for downscaled artwork. Never ship full-res art to a phone.
    artwork_poster_max_height: int = 500
    artwork_thumb_max_height: int = 200
    # JPEG quality used when re-encoding downscaled local artwork.
    artwork_jpeg_quality: int = 80
    # Max number of downscaled images held in the in-memory byte cache.
    artwork_cache_max_items: int = 256

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @field_validator("allowed_origins")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def monitored_paths_list(self) -> list[Path]:
        return [Path(p.strip()) for p in self.monitored_paths.split(",") if p.strip()]

    @property
    def monitored_services_list(self) -> list[str]:
        return [s.strip() for s in self.monitored_services.split(",") if s.strip()]

    @property
    def media_extensions_set(self) -> set[str]:
        return {
            e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
            for e in self.media_extensions.split(",")
            if e.strip()
        }

    @property
    def artwork_filenames_list(self) -> list[str]:
        return [f.strip() for f in self.artwork_filenames.split(",") if f.strip()]

    @property
    def jellyfin_enabled(self) -> bool:
        return bool(self.jellyfin_base_url.strip() and self.jellyfin_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (single load per process)."""

    return Settings()
