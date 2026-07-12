"""qBittorrent Web API client + status mapping.

Talks to the qBittorrent Web API (v2) over HTTP using ``httpx``. Authentication
is cookie-based: we log in once and reuse the ``SID`` cookie, transparently
re-authenticating if the session expires.

The service degrades gracefully: if qBittorrent is unreachable, the summary/list
responses come back with ``reachable=False`` and an explanatory message rather
than raising, so the dashboard still renders.

Reference: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.torrents import Torrent, TorrentsList, TorrentsSummary
from app.utils.formatting import human_bytes, human_duration

logger = get_logger(__name__)

# qBittorrent torrent state buckets.
_DOWNLOADING_STATES = {
    "downloading",
    "metaDL",
    "stalledDL",
    "queuedDL",
    "forcedDL",
    "checkingDL",
    "allocating",
}
_SEEDING_STATES = {"uploading", "stalledUP", "queuedUP", "forcedUP", "checkingUP"}
_COMPLETED_STATES = _SEEDING_STATES | {"pausedUP"}
_PAUSED_STATES = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}
_ERROR_STATES = {"error", "missingFiles"}


class QBittorrentError(RuntimeError):
    """Raised internally when the Web API cannot be reached/authenticated."""


class QBittorrentClient:
    """Minimal async client for the qBittorrent Web API.

    A single instance is shared across requests (see ``get_client``). It keeps a
    persistent ``httpx.AsyncClient`` whose cookie jar holds the session id.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.qbittorrent_url.rstrip("/")
        self._username = settings.qbittorrent_username
        self._password = settings.qbittorrent_password
        self._timeout = settings.qbittorrent_timeout
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                # qBittorrent checks the Referer/host for CSRF; setting the
                # Referer to the base URL satisfies it.
                headers={"Referer": self._base_url},
            )
        return self._client

    async def _login(self) -> None:
        client = await self._ensure_client()
        try:
            resp = await client.post(
                "/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
            )
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"connection failed: {exc}") from exc

        if resp.status_code == 403:
            raise QBittorrentError("login banned (too many failed attempts)")
        if resp.text.strip() != "Ok.":
            raise QBittorrentError("invalid credentials")
        self._authenticated = True

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        client = await self._ensure_client()
        async with self._lock:
            if not self._authenticated:
                await self._login()
        try:
            resp = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"connection failed: {exc}") from exc

        if resp.status_code == 403:
            # Session likely expired — re-auth once and retry.
            self._authenticated = False
            async with self._lock:
                await self._login()
            resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp

    async def fetch_torrents(self) -> list[dict]:
        resp = await self._get("/api/v2/torrents/info")
        return resp.json()

    async def _post(
        self,
        path: str,
        data: dict | None = None,
        files: dict | None = None,
    ) -> httpx.Response:
        client = await self._ensure_client()
        async with self._lock:
            if not self._authenticated:
                await self._login()
        try:
            resp = await client.post(path, data=data, files=files)
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"connection failed: {exc}") from exc

        if resp.status_code == 403:
            # Session likely expired — re-auth once and retry.
            self._authenticated = False
            async with self._lock:
                await self._login()
            resp = await client.post(path, data=data, files=files)
        resp.raise_for_status()
        return resp

    async def add_torrent(
        self,
        *,
        url: str | None = None,
        filename: str | None = None,
        file_bytes: bytes | None = None,
        category: str | None = None,
        save_path: str | None = None,
        paused: bool = False,
    ) -> None:
        """Add a torrent by magnet/URL or by uploading a ``.torrent`` file.

        Exactly one of ``url`` or (``filename`` + ``file_bytes``) must be
        given. Raises :class:`QBittorrentError` on transport failure or a
        non-2xx response; callers map that into a degraded response rather
        than letting it become a 500.
        """

        data: dict[str, str] = {}
        if category:
            data["category"] = category
        if save_path:
            data["savepath"] = save_path
        if paused:
            data["paused"] = "true"

        files = None
        if url is not None:
            data["urls"] = url
        elif filename is not None and file_bytes is not None:
            files = {"torrents": (filename, file_bytes, "application/x-bittorrent")}
        else:
            raise ValueError("add_torrent requires either url or filename+file_bytes")

        resp = await self._post("/api/v2/torrents/add", data=data, files=files)
        # qBittorrent returns 200 "Ok." even for some rejected torrents (e.g.
        # duplicate/invalid) — treat non-"Ok." bodies as failures.
        if resp.text.strip() != "Ok.":
            raise QBittorrentError(f"add torrent rejected: {resp.text.strip()}")

    async def stop_torrents(self, hashes: list[str]) -> None:
        """Pause (stop) torrents by hash.

        qBittorrent 5.x renamed ``pause`` → ``stop``; this instance's Web API
        (2.11.x) only exposes ``/stop``. Raises :class:`QBittorrentError` on
        transport failure.
        """

        if not hashes:
            return
        await self._post("/api/v2/torrents/stop", data={"hashes": "|".join(hashes)})

    async def start_torrents(self, hashes: list[str]) -> None:
        """Resume (start) torrents by hash (qBittorrent 5.x ``resume`` → ``start``)."""

        if not hashes:
            return
        await self._post("/api/v2/torrents/start", data={"hashes": "|".join(hashes)})

    async def delete_torrents(
        self, hashes: list[str], delete_files: bool = False
    ) -> None:
        """Remove torrents from qBittorrent by hash.

        With ``delete_files=False`` (the default) only the torrent *entry* is
        removed — the downloaded files are left on disk. Raises
        :class:`QBittorrentError` on transport failure; callers degrade rather
        than surfacing a 500.
        """

        if not hashes:
            return
        await self._post(
            "/api/v2/torrents/delete",
            data={
                "hashes": "|".join(hashes),
                "deleteFiles": "true" if delete_files else "false",
            },
        )

    async def fetch_version(self) -> str | None:
        """Return the qBittorrent application version (e.g. ``4.5.2``).

        Best-effort: returns ``None`` if the endpoint is unavailable so the
        summary can still populate the rest of its fields.
        """

        try:
            resp = await self._get("/api/v2/app/version")
        except (QBittorrentError, httpx.HTTPError) as exc:
            logger.warning("qBittorrent version lookup failed: %s", exc)
            return None
        return resp.text.strip().lstrip("v") or None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._authenticated = False


# --------------------------------------------------------------------------- #
# Module-level singleton client (created lazily, closed on app shutdown).
# --------------------------------------------------------------------------- #
_client: QBittorrentClient | None = None


def get_client(settings: Settings | None = None) -> QBittorrentClient:
    global _client
    if _client is None:
        _client = QBittorrentClient(settings or get_settings())
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


# --------------------------------------------------------------------------- #
# Mapping helpers
# --------------------------------------------------------------------------- #
def _map_torrent(raw: dict) -> Torrent:
    progress = float(raw.get("progress", 0.0))
    eta = raw.get("eta")
    # qBittorrent uses 8640000 (100 days) to mean "infinity/unknown".
    eta_seconds = None if eta in (None, 8640000) else int(eta)
    added_on = raw.get("added_on")
    added_iso = (
        datetime.fromtimestamp(added_on, tz=timezone.utc).isoformat()
        if added_on
        else None
    )
    dlspeed = int(raw.get("dlspeed", 0))
    upspeed = int(raw.get("upspeed", 0))

    return Torrent(
        hash=raw.get("hash", ""),
        name=raw.get("name", "unknown"),
        state=raw.get("state", "unknown"),
        category=raw.get("category") or None,
        progress=round(progress, 4),
        progress_percent=round(progress * 100, 1),
        size_bytes=int(raw.get("size", 0)),
        size_human=human_bytes(raw.get("size", 0)),
        downloaded_bytes=int(raw.get("downloaded", 0)),
        dlspeed_bytes=dlspeed,
        upspeed_bytes=upspeed,
        dlspeed_human=f"{human_bytes(dlspeed)}/s",
        upspeed_human=f"{human_bytes(upspeed)}/s",
        eta_seconds=eta_seconds,
        eta_human=human_duration(eta_seconds) if eta_seconds is not None else None,
        ratio=round(float(raw.get("ratio", 0.0)), 3),
        num_seeds=int(raw.get("num_seeds", 0)),
        num_leechs=int(raw.get("num_leechs", 0)),
        added_on_iso=added_iso,
    )


async def get_torrents_list(
    settings: Settings | None = None, state_filter: str | None = None
) -> TorrentsList:
    """Return the full torrent list, optionally filtered by a coarse bucket.

    ``state_filter`` accepts: ``downloading``, ``seeding``, ``completed``.
    """

    client = get_client(settings)
    try:
        raw = await client.fetch_torrents()
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("qBittorrent unreachable: %s", exc)
        return TorrentsList(reachable=False, count=0, torrents=[], message=str(exc))

    torrents = [_map_torrent(t) for t in raw]

    if state_filter == "downloading":
        torrents = [t for t in torrents if t.state in _DOWNLOADING_STATES]
    elif state_filter == "seeding":
        torrents = [t for t in torrents if t.state in _SEEDING_STATES]
    elif state_filter == "completed":
        torrents = [t for t in torrents if t.progress >= 1.0]

    return TorrentsList(reachable=True, count=len(torrents), torrents=torrents)


async def get_torrents_summary(settings: Settings | None = None) -> TorrentsSummary:
    """Aggregate counts and speeds across all torrents."""

    client = get_client(settings)
    try:
        raw = await client.fetch_torrents()
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("qBittorrent unreachable: %s", exc)
        return TorrentsSummary(reachable=False, message=str(exc))

    summary = TorrentsSummary(reachable=True, total=len(raw))
    # Client identity (spec §3.1). qBittorrent is the client here; the version
    # is a cheap extra call that degrades to null if it fails. ``node`` is not
    # applicable for this single-instance setup.
    summary.client_name = "qBittorrent"
    summary.client_version = await client.fetch_version()
    for t in raw:
        state = t.get("state", "")
        summary.total_dlspeed_bytes += int(t.get("dlspeed", 0))
        summary.total_upspeed_bytes += int(t.get("upspeed", 0))
        if state in _DOWNLOADING_STATES:
            summary.downloading += 1
        if state in _SEEDING_STATES:
            summary.seeding += 1
        if float(t.get("progress", 0.0)) >= 1.0:
            summary.completed += 1
        if state in _PAUSED_STATES:
            summary.paused += 1
        if state in _ERROR_STATES:
            summary.error += 1

    summary.total_dlspeed_human = f"{human_bytes(summary.total_dlspeed_bytes)}/s"
    summary.total_upspeed_human = f"{human_bytes(summary.total_upspeed_bytes)}/s"
    return summary


# NOTE (future control endpoints): pause/resume/delete map to
# POST /api/v2/torrents/pause|resume|delete with a `hashes` form field. Add them
# as further methods here (see `add_torrent` above for the pattern) and expose
# behind the authenticated /api/v1/actions router
# (app/api/routes/actions.py, app/services/torrent_control_service.py).
