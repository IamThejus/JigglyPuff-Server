"""Library artwork resolution + proxy/stream.

Two sources, one contract (spec §1.4). Whatever the source, the app only ever
sees a ``poster_url`` (or ``null``) per item plus the ``/library/artwork``
endpoint that returns the bytes:

* **Option A — Jellyfin (preferred).** When ``JELLYFIN_BASE_URL`` +
  ``JELLYFIN_API_KEY`` are set, a folder→Jellyfin-item mapping is cached and
  refreshed on a timer; ``poster_url`` points at ``?id=<jellyfin_id>`` and the
  artwork endpoint proxies + downscales the poster from Jellyfin.
* **Option B — Local files.** Otherwise the backend looks for
  ``poster.jpg`` / ``folder.jpg`` / ``cover.jpg`` next to each title;
  ``poster_url`` points at ``?path=<folder>`` and the endpoint reads + downscales
  that file.

Both degrade to ``poster_url: null`` (never an error) when nothing is available
— the app treats ``null`` as "show the placeholder" (spec §0.2).

Building ``poster_url`` in the list path is O(1) string work backed by caches;
no per-request Jellyfin calls or uncached ffmpeg/hashing happen there (§4).
"""

from __future__ import annotations

import mimetypes
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

try:  # Pillow is optional; without it we serve local art without downscaling.
    from PIL import Image  # type: ignore

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - Pillow not installed
    Image = None  # type: ignore
    _PIL_AVAILABLE = False

logger = get_logger(__name__)

# Full path the app calls (router prefix "/library" under the "/api/v1" mount).
_ARTWORK_PATH = "/api/v1/library/artwork"

_VALID_SIZES = ("poster", "thumb")


@dataclass(frozen=True)
class ArtworkRef:
    """What the list path attaches to each item."""

    poster_url: str | None = None
    thumb_url: str | None = None
    jellyfin_id: str | None = None
    # Jellyfin's own title/year for the matched item, if any — strictly
    # better than filename-regex parsing. Callers (currently movies only,
    # see library_service.py) may use these to override filesystem-derived
    # name/year.
    jellyfin_name: str | None = None
    jellyfin_year: int | None = None


@dataclass(frozen=True)
class ArtworkBytes:
    """A resolved, downscaled image ready to stream."""

    content: bytes
    content_type: str
    etag: str


@dataclass(frozen=True)
class _JellyfinEntry:
    id: str
    tag: str | None
    name: str | None = None
    year: int | None = None


class ArtworkService:
    """Resolves poster URLs for the list path and streams the bytes on demand.

    A single instance is shared per process (see ``get_artwork_service``).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # folder→Jellyfin item, refreshed on a timer.
        self._by_path: dict[str, _JellyfinEntry] = {}
        self._by_name_year: dict[tuple[str, int], _JellyfinEntry] = {}
        self._by_name: dict[str, _JellyfinEntry] = {}
        self._jellyfin_map_expires = 0.0
        # per-folder local-artwork filename (or None) with an expiry.
        self._local_cache: dict[str, tuple[float, str | None]] = {}
        # downscaled bytes keyed by (source_key, size).
        self._byte_cache: "OrderedDict[tuple[str, str], ArtworkBytes]" = OrderedDict()
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ #
    # List path — cheap, cached resolution
    # ------------------------------------------------------------------ #
    def resolve(self, path: str, name: str, year: int | None) -> ArtworkRef:
        """Return the artwork reference for a library item.

        O(1) string work plus cached lookups only — safe to call per item even
        on the fast (``sizes=false``) path.
        """

        # Prefer Jellyfin when we have a mapping for this item.
        entry = self._match_jellyfin(path, name, year)
        if entry is not None:
            return ArtworkRef(
                poster_url=self._url(id=entry.id, size="poster"),
                thumb_url=self._url(id=entry.id, size="thumb"),
                jellyfin_id=entry.id,
                jellyfin_name=entry.name,
                jellyfin_year=entry.year,
            )

        # Otherwise fall back to a local artwork file next to the title.
        if self._local_artwork_name(path) is not None:
            return ArtworkRef(
                poster_url=self._url(path=path, size="poster"),
                thumb_url=self._url(path=path, size="thumb"),
                jellyfin_id=None,
            )

        return ArtworkRef()

    def _url(
        self, *, size: str, id: str | None = None, path: str | None = None
    ) -> str:
        params = {"id": id} if id is not None else {"path": path}
        params["size"] = size
        return f"{_ARTWORK_PATH}?{urlencode(params)}"

    def _match_jellyfin(
        self, path: str, name: str, year: int | None
    ) -> _JellyfinEntry | None:
        if not self._by_path and not self._by_name:
            return None
        # 1) Exact filesystem path (reliable on the Dell where the API and
        #    Jellyfin see the same paths).
        entry = self._by_path.get(_norm_path(path))
        if entry is not None:
            return entry
        # 2) Clean title (+year), since folder names carry release junk
        #    ("The.Dark.Knight.Rises.2012.2160p...") that Jellyfin's title
        #    ("The Dark Knight Rises") does not.
        title = _clean_title(name)
        if year is not None:
            entry = self._by_name_year.get((title, year))
            if entry is not None:
                return entry
        return self._by_name.get(title)

    def _local_artwork_name(self, folder: str) -> str | None:
        """Name of the first existing local artwork file in ``folder`` (cached)."""

        now = time.monotonic()
        cached = self._local_cache.get(folder)
        if cached is not None and cached[0] > now:
            return cached[1]

        found: str | None = None
        base = Path(folder)
        if base.is_dir():
            for candidate in self._settings.artwork_filenames_list:
                if (base / candidate).is_file():
                    found = candidate
                    break
        self._local_cache[folder] = (now + self._settings.artwork_local_ttl, found)
        return found

    # ------------------------------------------------------------------ #
    # Jellyfin mapping refresh (async, best-effort)
    # ------------------------------------------------------------------ #
    async def ensure_jellyfin_map(self) -> None:
        """Refresh the folder→Jellyfin mapping if enabled and stale.

        Never raises: on any error the mapping is left empty (or stale) so the
        list path degrades to local files / ``null`` rather than failing.
        """

        if not self._settings.jellyfin_enabled:
            return
        if time.monotonic() < self._jellyfin_map_expires and self._by_name:
            return

        try:
            client = await self._ensure_client()
            resp = await client.get(
                f"{self._settings.jellyfin_base_url.rstrip('/')}/Items",
                params={
                    "api_key": self._settings.jellyfin_api_key,
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series",
                    "Fields": "Path",
                    "ImageTypeLimit": 1,
                    "EnableImageTypes": "Primary",
                },
            )
            resp.raise_for_status()
            items = resp.json().get("Items", [])
        except Exception as exc:  # noqa: BLE001 - degrade, never fail
            logger.warning("Jellyfin mapping refresh failed: %s", exc)
            # Keep any previous mapping; back off for the TTL before retrying.
            self._jellyfin_map_expires = time.monotonic() + self._settings.jellyfin_map_ttl
            return

        by_path: dict[str, _JellyfinEntry] = {}
        by_name_year: dict[tuple[str, int], _JellyfinEntry] = {}
        by_name: dict[str, _JellyfinEntry] = {}
        ambiguous_parents: set[str] = set()
        for item in items:
            item_id = item.get("Id")
            if not item_id:
                continue
            tag = (item.get("ImageTags") or {}).get("Primary")
            name = item.get("Name")
            year = item.get("ProductionYear")
            year = year if isinstance(year, int) else None
            entry = _JellyfinEntry(id=str(item_id), tag=tag, name=name, year=year)
            item_path = item.get("Path")
            if item_path:
                norm = _norm_path(item_path)
                by_path[norm] = entry
                # Jellyfin's Path may be the video file itself; index its parent
                # folder too so it matches our folder-level library item. A
                # release folder can contain more than one video (the real
                # movie plus a junk/sample/extras file) — if two *different*
                # Jellyfin items share a parent, guessing which one is "the
                # movie" would be a coin flip (whichever the API happened to
                # return first). Back out of the shortcut entirely for that
                # folder instead, so matching falls through to the
                # clean-title tier below, which keys off each item's own
                # Name and won't confuse e.g. a release-group sample clip
                # with the actual film.
                parent = _norm_path(str(Path(item_path).parent))
                if parent in ambiguous_parents:
                    pass
                elif parent in by_path and by_path[parent].id != entry.id:
                    del by_path[parent]
                    ambiguous_parents.add(parent)
                else:
                    by_path.setdefault(parent, entry)
            if name:
                title = _clean_title(name)
                by_name[title] = entry
                if year is not None:
                    by_name_year[(title, year)] = entry

        self._by_path = by_path
        self._by_name_year = by_name_year
        self._by_name = by_name
        self._jellyfin_map_expires = time.monotonic() + self._settings.jellyfin_map_ttl
        logger.info("Jellyfin mapping refreshed: %d items", len(by_name))

    # ------------------------------------------------------------------ #
    # Byte fetch (used by the /library/artwork endpoint)
    # ------------------------------------------------------------------ #
    async def fetch(
        self, *, size: str, id: str | None = None, path: str | None = None
    ) -> ArtworkBytes | None:
        """Return downscaled image bytes, or ``None`` when art is missing.

        ``None`` maps to a 404 at the route layer (spec §1.3); it is never an
        error/500.
        """

        if size not in _VALID_SIZES:
            size = "poster"
        max_height = (
            self._settings.artwork_poster_max_height
            if size == "poster"
            else self._settings.artwork_thumb_max_height
        )

        cache_key = (id or path or "", size)
        cached = self._byte_cache.get(cache_key)
        if cached is not None:
            self._byte_cache.move_to_end(cache_key)
            return cached

        result: ArtworkBytes | None = None
        if id is not None and self._settings.jellyfin_enabled:
            result = await self._fetch_jellyfin(id, max_height)
        elif path is not None:
            result = self._fetch_local(path, max_height)

        if result is not None:
            self._byte_cache[cache_key] = result
            self._byte_cache.move_to_end(cache_key)
            while len(self._byte_cache) > self._settings.artwork_cache_max_items:
                self._byte_cache.popitem(last=False)
        return result

    async def _fetch_jellyfin(self, item_id: str, max_height: int) -> ArtworkBytes | None:
        tag = None
        for entry in self._by_name.values():
            if entry.id == item_id:
                tag = entry.tag
                break
        params: dict[str, object] = {
            "maxHeight": max_height,
            "api_key": self._settings.jellyfin_api_key,
        }
        if tag:
            params["tag"] = tag
        url = (
            f"{self._settings.jellyfin_base_url.rstrip('/')}"
            f"/Items/{item_id}/Images/Primary"
        )
        try:
            client = await self._ensure_client()
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - missing art is not an error
            logger.warning("Jellyfin artwork fetch failed (id=%s): %s", item_id, exc)
            return None

        content = resp.content
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        version = tag or resp.headers.get("ETag") or _weak_token(content)
        etag = f'"{item_id}-{max_height}-{version}"'
        return ArtworkBytes(content=content, content_type=content_type, etag=etag)

    def _fetch_local(self, folder: str, max_height: int) -> ArtworkBytes | None:
        name = self._local_artwork_name(folder)
        if name is None:
            return None
        file_path = Path(folder) / name
        try:
            stat = file_path.stat()
            raw = file_path.read_bytes()
        except OSError as exc:
            logger.warning("local artwork read failed (%s): %s", file_path, exc)
            return None

        content, content_type = _downscale(
            raw,
            fallback_type=_guess_type(name),
            max_height=max_height,
            quality=self._settings.artwork_jpeg_quality,
        )
        etag = f'"{stat.st_mtime_ns}-{len(content)}-{max_height}"'
        return ArtworkBytes(content=content, content_type=content_type, etag=etag)

    # ------------------------------------------------------------------ #
    # Shared HTTP client lifecycle
    # ------------------------------------------------------------------ #
    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# --------------------------------------------------------------------------- #
# Module-level singleton
# --------------------------------------------------------------------------- #
_service: ArtworkService | None = None


def get_artwork_service(settings: Settings | None = None) -> ArtworkService:
    global _service
    if _service is None:
        _service = ArtworkService(settings or get_settings())
    return _service


async def close_artwork_service() -> None:
    global _service
    if _service is not None:
        await _service.close()
        _service = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _norm_path(path: str) -> str:
    return path.rstrip("/").lower()


# Release-junk that marks the end of the real title in a folder name.
_TITLE_STOP_RE = re.compile(
    r"[.\s_(\[]+(?:(?:19|20)\d{2}|2160p|1080p|720p|480p|4k|bluray|web[-.]?dl|"
    r"webrip|hdrip|bdrip|dvdrip|x264|x265|h264|h265|hevc|hdr10\+?|hdr|dv|"
    r"remux|proper|repack|amzn|nf|dsnp)\b.*$",
    re.IGNORECASE,
)


def _clean_title(name: str) -> str:
    """Normalise a folder/title into a lowercase key for fuzzy matching.

    ``The.Dark.Knight.Rises.2012.2160p.HDR.BluRay.x265`` -> ``the dark knight
    rises``. Jellyfin titles are already clean, so lowercasing them lands on the
    same key.
    """

    cleaned = _TITLE_STOP_RE.sub("", name)
    cleaned = cleaned.replace(".", " ").replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned.lower()


def _guess_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "image/jpeg"


def _weak_token(data: bytes) -> str:
    # Cheap, stable-per-content token for an ETag (not a security hash).
    return f"{len(data)}-{hash(data) & 0xFFFFFFFF:08x}"


def _downscale(
    data: bytes, *, fallback_type: str, max_height: int, quality: int
) -> tuple[bytes, str]:
    """Downscale ``data`` to ``max_height`` if Pillow is available.

    Falls back to the original bytes (and their guessed type) when Pillow is
    missing or the image can't be processed — the endpoint still works, it just
    ships the original resolution.
    """

    if not _PIL_AVAILABLE:
        return data, fallback_type
    try:
        import io

        with Image.open(io.BytesIO(data)) as img:
            if img.height > max_height:
                ratio = max_height / float(img.height)
                new_size = (max(1, round(img.width * ratio)), max_height)
                img = img.resize(new_size, Image.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality)
            return out.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001 - fall back to original bytes
        logger.warning("artwork downscale failed: %s", exc)
        return data, fallback_type
