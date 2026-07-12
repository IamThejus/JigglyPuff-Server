"""Trigger for the existing ``sync-movies`` shell script, plus torrent cleanup.

The script (deployed at ``settings.sync_movies_script_path`` on the Dell)
moves completed downloads from the torrents "complete" folder into the
movies library, printing ``Moving: <name>`` / ``Skipping: <name>`` per item.
Its move/skip logic isn't duplicated here — this module shells out to it via
``app.utils.shell.run`` (a fixed path, no interpolated arguments, so there's
no injection surface).

After a successful run we also remove the qBittorrent *entries* for the items
that were moved: once ``mv``'d into the library, their old
``complete/<name>`` path is empty, so the torrent just clutters the list. We
delete metadata only (``deleteFiles=false``) — the moved movie is preserved.
Items the script *skipped* (already in the library) are left untouched.
"""

from __future__ import annotations

import os

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.actions import SyncMoviesResponse
from app.services.qbittorrent_service import QBittorrentError, get_client
from app.utils import shell

logger = get_logger(__name__)

_MOVING_PREFIX = "Moving: "
_SKIPPING_PREFIX = "Skipping: "
# The script appends this to skipped lines: "Skipping: <name> (already ...)".
_SKIPPING_SUFFIX = " (already exists in movies)"


def _parse_script_output(output: str) -> tuple[list[str], list[str]]:
    """Return ``(moved, skipped)`` item names parsed from the script's stdout.

    ``Moving: <name>`` lines carry a clean basename; ``Skipping: <name>``
    lines carry a known trailing suffix we strip. Only ``moved`` drives
    torrent cleanup — ``skipped`` is informational.
    """

    moved: list[str] = []
    skipped: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(_MOVING_PREFIX):
            moved.append(line[len(_MOVING_PREFIX) :].strip())
        elif line.startswith(_SKIPPING_PREFIX):
            name = line[len(_SKIPPING_PREFIX) :].strip()
            if name.endswith(_SKIPPING_SUFFIX):
                name = name[: -len(_SKIPPING_SUFFIX)].strip()
            skipped.append(name)
    return moved, skipped


async def _remove_moved_torrents(
    moved: list[str], settings: Settings
) -> tuple[int, str | None]:
    """Remove qBittorrent entries whose content was moved this run.

    Matches by ``basename(content_path)`` (not torrent name — they differ),
    restricted to torrents saved under the complete/ folder. Returns
    ``(removed_count, message)``; ``message`` is set only when cleanup was
    skipped because qBittorrent was unreachable (the move itself still
    succeeded, so this never fails the request).
    """

    client = get_client(settings)
    try:
        raw = await client.fetch_torrents()
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("sync-movies: torrent cleanup skipped (qBittorrent down): %s", exc)
        return 0, f"moved files, but torrent cleanup skipped: {exc}"

    complete_root = os.path.normpath(str(settings.torrents_complete_path))
    moved_set = set(moved)
    hashes: list[str] = []
    for t in raw:
        content_path = t.get("content_path", "")
        if not content_path:
            continue
        cp = os.path.normpath(content_path)
        # Only touch torrents whose content lives under the complete/ folder —
        # never a same-named torrent living elsewhere.
        if cp != complete_root and not cp.startswith(complete_root + os.sep):
            continue
        # The script moves each *top-level* entry under complete/ (its
        # `for item in "$SOURCE"/*`). qBittorrent's content_path may point
        # deeper (e.g. a single file wrapped in a folder →
        # `.../complete/<folder>/movie.mkv`), so match on the first path
        # segment under complete/, which is exactly the item name the script
        # prints in its `Moving:` line — not `basename(content_path)`.
        top_segment = os.path.relpath(cp, complete_root).split(os.sep)[0]
        if top_segment in moved_set:
            h = t.get("hash")
            if h:
                hashes.append(h)

    if not hashes:
        return 0, None

    try:
        await client.delete_torrents(hashes, delete_files=False)
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("sync-movies: torrent delete failed: %s", exc)
        return 0, f"moved files, but torrent removal failed: {exc}"

    return len(hashes), None


async def run_sync_movies(settings: Settings | None = None) -> SyncMoviesResponse:
    settings = settings or get_settings()

    result = shell.run(
        [settings.sync_movies_script_path], timeout=settings.sync_movies_timeout
    )

    if not result.ok:
        logger.warning("sync-movies failed: %s", result.stderr or result.output)
        return SyncMoviesResponse(
            ok=False,
            exit_code=result.returncode,
            output=result.output,
            message=result.stderr.strip() or "sync-movies failed",
        )

    moved, skipped = _parse_script_output(result.output)

    torrents_removed = 0
    message: str | None = None
    if moved:
        torrents_removed, message = await _remove_moved_torrents(moved, settings)

    return SyncMoviesResponse(
        ok=True,
        exit_code=result.returncode,
        output=result.output,
        message=message,
        moved=moved,
        skipped=skipped,
        torrents_removed=torrents_removed,
    )
