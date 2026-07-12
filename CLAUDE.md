# CLAUDE.md

Guidance for Claude Code (or any future contributor) working in this repo.

## What this project is

`media-server-api` is a **read-only FastAPI backend** that runs on a Debian
Dell home server and feeds a mobile app ("JigglyPuff") status/media data over
the LAN (or remotely). It exposes system health, storage, torrent status,
media library listings + artwork, and systemd service status. **v1 has no auth
and no write/control endpoints** — everything is `GET`.

The mobile app is the only consumer. It parses defensively — missing fields
fall back to `null`/`0`/`""` — so the API can add fields/endpoints without
coordinated deploys, but existing fields must never be renamed or removed
(see "Hard invariants" below).

## Architecture

```
routes (app/api/routes/*.py)   — thin HTTP layer: parse query params, call a
                                  service, return its typed schema. No OS/
                                  filesystem/network calls here.
        ↓
services (app/services/*.py)   — all integration logic: filesystem scans,
                                  psutil, systemctl, smartctl, qBittorrent Web
                                  API, Jellyfin API. Each returns a Pydantic
                                  schema, never raises for expected failure
                                  modes (unreachable service, missing device,
                                  missing file) — it returns a degraded but
                                  valid response instead.
        ↓
schemas (app/schemas/*.py)     — Pydantic response models. One file per
                                  domain, named after the domain (library.py,
                                  torrents.py, storage.py, system.py,
                                  services.py, dashboard.py).

app/core/config.py              — pydantic-settings Settings, env-driven,
                                   cached via get_settings() (lru_cache).
app/core/logging.py              — stdlib logging setup, configured once at
                                   startup.
app/utils/                      — shared, dependency-free helpers
                                   (formatting.py: human_bytes/human_duration/
                                   percent; shell.py: subprocess wrapper;
                                   media_metadata.py: filename parsing).
app/main.py                     — FastAPI app factory, CORS, router wiring,
                                   lifespan (startup/shutdown of shared HTTP
                                   clients).
```

Routes never touch the OS/network directly — that discipline is what keeps
the HTTP layer trivial and the integration logic independently testable.
Follow it for any new endpoint.

## Hard invariants (do not break these)

These come from the original API-upgrade spec and still apply to any future
change:

1. **Additive & backwards compatible.** Only add fields/endpoints. Never
   rename or remove an existing field — the app has partial-rollout tolerance
   baked in (missing → `null`/`0`/`""`), but only in the "add" direction.
2. **Never fail when a subsystem is down.** If qBittorrent / Jellyfin / SMART
   / systemd is unreachable, the endpoint still returns `200` with the normal
   shape, degraded fields set to `null`/`false`/empty-list, and optionally a
   `message`. Never raise `500` for an external dependency being down. Every
   service module in this repo follows this pattern already — copy it.
3. **`*_human` strings stay pre-formatted.** Fields like `uptime_human`,
   `eta_human`, `size_human`, `total_dlspeed_human` are displayed verbatim by
   the app. The raw `*_bytes`/`*_percent`/`*_seconds` numbers exist so the app
   can drive bars/gauges. Never collapse this split — always add both a raw
   and a `_human` field together for anything size/duration-like (see
   `app/utils/formatting.py`).
4. **`snake_case` field names**, matching the existing style throughout.
5. **Keep list paths fast.** `GET /library/movies|shows` accept `sizes=false`
   to skip the (expensive, `os.walk`-based) per-item folder size computation.
   Anything added to the list path must be O(1) or backed by a
   timer-refreshed cache — never a per-request network call or filesystem
   walk. `poster_url`/`thumb_url`/`year`/`quality`/`hdr` all follow this rule
   (see `app/services/artwork_service.py` and `media_metadata.py`).
6. **No shell injection.** All subprocess calls go through
   `app/utils/shell.run()`, which takes an argument list — never build a
   shell string. Extend `shell.py` rather than calling `subprocess` directly
   elsewhere.

## Endpoints at a glance

All mounted under `/api/v1`. See README.md for full request/response detail
per endpoint — this is just the map.

| Endpoint | Service module | Notes |
|---|---|---|
| `GET /health` | — (inline in route) | liveness probe, app splash |
| `GET /dashboard` | `dashboard_service.py` | fans out to system/storage/torrents/library/services and composes one summary |
| `GET /torrents/summary`, `/torrents/list` | `qbittorrent_service.py` | qBittorrent Web API v2 client, cookie-session auth |
| `GET /storage/summary` | `storage_service.py` | `shutil.disk_usage` + `os.walk` folder sizes + `smartctl -j` |
| `GET /system/overview` | `system_service.py` | `psutil` + `platform` — CPU/mem/swap/temps/battery/interfaces |
| `GET /library/summary`, `/movies`, `/shows` | `library_service.py` | filesystem scan of `movies_path`/`shows_path`, one item per top-level entry |
| `GET /library/artwork` | `artwork_service.py` | poster/thumbnail proxy — see below |
| `GET /services` | `service_status_service.py` | `systemctl show` per configured unit |

## Library artwork subsystem (the newest, most involved piece)

`app/services/artwork_service.py` gives every `MediaItem` a `poster_url` /
`thumb_url` (or `null`) and backs the `GET /library/artwork` endpoint. Two
sources, same contract:

- **Jellyfin (preferred)** — enabled when both `JELLYFIN_BASE_URL` and
  `JELLYFIN_API_KEY` are set (`Settings.jellyfin_enabled`). A folder→Jellyfin
  item mapping is fetched from Jellyfin's `/Items` endpoint and cached for
  `JELLYFIN_MAP_TTL` seconds (`ensure_jellyfin_map`, called from the library
  routes before every list/summary response — cheap because it's a no-op once
  warm). Matching tries, in order: **exact filesystem path** (and the parent
  directory of Jellyfin's `Path`, since Jellyfin may report the video file
  rather than the folder), then **clean title + year**, then **clean title
  alone**. "Clean title" strips release-junk tokens (resolution, codec, HDR,
  source, year) via `_clean_title()` — this exists because folder names look
  like `The.Dark.Knight.Rises.2012.2160p.HDR.BluRay.x265` while Jellyfin's
  title is `The Dark Knight Rises`.
- **Local files (fallback)** — checked when there's no Jellyfin match:
  `poster.jpg` / `poster.png` / `poster.webp` / `folder.jpg` / `folder.png` /
  `cover.jpg` / `cover.png` (in that order, `ARTWORK_FILENAMES`) next to the
  item. Existence is cached per-folder for `ARTWORK_LOCAL_TTL` seconds.
- **Neither available** → `poster_url: null`, `jellyfin_id: null`. Normal
  state, not an error — the app shows its placeholder gradient.

The `GET /library/artwork?id=<jellyfin_id>|path=<folder>&size=poster|thumb`
endpoint resolves those refs to bytes: Jellyfin bytes are proxied from
`/Items/{id}/Images/Primary?maxHeight=…`; local files are read and downscaled
with Pillow (optional dependency — falls back to serving the original file
untouched if Pillow isn't installed). Downscaled bytes are cached in an
in-memory LRU (`artwork_cache_max_items`) keyed by `(id|path, size)`. Response
carries `Cache-Control: public, max-age=86400` + `ETag`; honors
`If-None-Match` → `304`. Missing art → `404`, never `500`.

`year` / `quality` / `hdr` come from `app/utils/media_metadata.py`, which
regex-parses the same release-junk folder names (first `19xx`/`20xx` token for
year, `2160p`/`4K`→`2160p`/`1080p`/`720p`/`480p` for quality, `HDR`/`DV`/
`DoVi`/`HDR10` presence for `hdr`). Pure function, no I/O, always populated —
independent of whether artwork resolution succeeds.

When touching this subsystem: **the list path (`resolve()`) must stay
synchronous and cache-only** — it's called once per item on every
`/library/*` request. Only `ensure_jellyfin_map()` (called once per request,
not per item) and `fetch()` (called once per artwork request) are async/do
I/O.

## Config

Everything is `pydantic-settings`, loaded from the process environment or a
local `.env` (see `.env.example` for the full annotated list, and
`app/core/config.py` for defaults/derived properties like
`cors_origins`/`monitored_paths_list`/`jellyfin_enabled`). `.env` is
git-ignored — real credentials/paths live only on the Dell and the dev
machine, never committed. `get_settings()` is `lru_cache`d — call
`get_settings.cache_clear()` if you need to reload settings mid-process (e.g.
in tests that mutate env vars).

## Extending this API

- New read-only integration → new `services/*_service.py` module following
  the existing degrade-don't-fail pattern, a schema in `schemas/`, a thin
  route in `api/routes/`, wired into `main.py`'s router list.
- **Control/write endpoints are out of scope for v1** by design. If adding
  them later: put write logic in new modules (e.g. `torrent_control_service.py`)
  — leave read-only modules untouched — mount under a separate
  `/api/v1/actions` router, and gate behind auth. Extension points are marked
  with `NOTE (future control endpoints)` comments in
  `qbittorrent_service.py` and `service_status_service.py`.
- When adding a field that the mobile app needs to consume, also update the
  mobile-facing changelog pattern used in `API_CHANGES_MOBILE.md` (see repo
  root next to this file if present, or create one) so the app team has a
  single diff to read instead of the full spec.

## Local dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

On a non-Dell machine, media/download paths won't exist and qBittorrent/
Jellyfin will be unreachable — that's expected and everything should still
return `200` with degraded fields (this is the behavior to verify after any
change, not an error to "fix"). Point `MOVIES_PATH`/`SHOWS_PATH` at a local
folder with subfolders (optionally containing a `poster.jpg`) to exercise the
library/artwork paths for real.
