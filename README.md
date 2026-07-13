# JigglyPuff-Server

The **FastAPI** backend for **JigglyPuff**, a Dell Debian home media server
dashboard app. This repo (**JigglyPuff-Server**) serves system, storage,
torrent, library, and service status to the JigglyPuff mobile app over the
LAN (or remotely), plus a small set of authenticated control actions (add a
torrent, trigger `sync-movies`) and a WebSocket for real-time torrent
progress.

**Everything except `/api/v1/actions/*` is read-only and unauthenticated.**
Control actions require an `X-API-Key` header (see
[Configuration](#configuration)). See [Extending](#extending) for how future
control endpoints should be added, and [CLAUDE.md](CLAUDE.md) for the
condensed architecture reference used when working on this repo with Claude
Code.

---

## Features

| Area      | Source                              | Endpoint(s)                                        |
|-----------|-------------------------------------|----------------------------------------------------|
| Health    | app                                 | `GET /api/v1/health`                               |
| Dashboard | aggregates everything below         | `GET /api/v1/dashboard`                            |
| Torrents  | qBittorrent Web API                 | `GET /api/v1/torrents/summary`, `/torrents/list`, `GET /torrents/ws` (WebSocket) |
| Storage   | `shutil` / `psutil` / `smartctl`    | `GET /api/v1/storage/summary`                      |
| System    | `psutil` / `platform`               | `GET /api/v1/system/overview`                      |
| Library   | filesystem scan                     | `GET /api/v1/library/summary`, `/movies`, `/shows` |
| Artwork   | Jellyfin proxy / local files        | `GET /api/v1/library/artwork`                      |
| Services  | `systemctl`                         | `GET /api/v1/services`                             |
| Actions 🔒 | qBittorrent Web API / `sync-movies` script | `POST /api/v1/actions/torrents`, `/torrents/file`, `/torrents/pause`, `/torrents/resume`, `/torrents/delete`, `/sync-movies` |

> 🔒 = requires `X-API-Key` header.

> All routes are mounted under the `/api/v1` prefix for versioning.
> Interactive docs: `http://<host>:8000/docs`.

---

## Project structure

```text
JigglyPuff-Server/
├─ app/
│  ├─ main.py                 # app factory, CORS, router wiring, lifespan
│  ├─ core/
│  │  ├─ config.py            # env-driven settings (pydantic-settings)
│  │  └─ logging.py
│  ├─ api/routes/             # thin HTTP layer, one file per domain
│  ├─ services/               # system integration / business logic
│  ├─ schemas/                # Pydantic response models
│  └─ utils/                  # shell wrapper, formatting, filename metadata
├─ requirements.txt
├─ .env.example
├─ media-server-api.service   # systemd unit for the Dell
├─ CLAUDE.md                  # architecture reference for Claude Code
└─ README.md
```

**Layering:** `routes → services → schemas`. Routes never touch the OS or
network directly; every system/filesystem/HTTP call lives in a `services/*`
module and returns a typed Pydantic schema. This keeps the HTTP layer trivial
and the integration logic independently testable.

**Degrade, don't fail.** Every service module follows the same rule: if the
thing it talks to (qBittorrent, Jellyfin, `smartctl`, `systemctl`) is down or
misconfigured, the function returns a normal, typed response with the
relevant fields set to `null`/`false`/empty — it does not raise. Routes never
see (and never need to handle) that failure mode; it's absorbed one layer
down. This is why every endpoint below returns `200` even when its backing
subsystem is unreachable.

---

## API reference

Full request/response detail for every endpoint, in the order listed in
[Features](#features). All are `GET`, mounted under `/api/v1`, and return
`200` on success — see each entry for its specific failure/degradation
behavior.

### `GET /api/v1/health`

Liveness probe / app splash-screen check. No dependencies, always `200`.

```jsonc
{ "status": "ok", "version": "1.0.0", "time": "2026-07-10T12:00:00+00:00" }
```

### `GET /api/v1/dashboard`

The mobile app's home-screen call. Fans out to system, storage, torrents,
library, and services, and composes one summary (`app/services/dashboard_service.py`).
Torrents is the only async call in the fan-out; the rest are quick
synchronous `psutil`/filesystem reads.

```jsonc
{
  "hostname": "dell-server",
  "server_name": "Dell Media Server",
  "uptime_seconds": 123456, "uptime_human": "1d 10h 17m",
  "cpu_percent": 12.3, "memory_percent": 41.0, "disk_percent_used": 67.2,
  "storage": { "primary_path": "/srv/storage", "total_human": "...", "used_human": "...", "free_human": "...", "percent_used": 67.2 },
  "torrents_active": 3, "torrents_downloading": 1, "torrents_seeding": 2, "torrents_reachable": true,
  "movies_count": 214, "shows_count": 58,
  "services": [ { "name": "jellyfin", "active": true, "state": "active", "sub_state": "running", "enabled": true } ],
  "generated_at_iso": "2026-07-10T12:00:00+00:00"
}
```

If qBittorrent is unreachable, `torrents_reachable: false` and the torrent
counts are `0` — nothing else in the payload is affected.

### `GET /api/v1/torrents/summary`

Aggregate counts + speeds from qBittorrent (`app/services/qbittorrent_service.py`,
qBittorrent Web API v2, cookie-session auth, auto re-login on session expiry).

```jsonc
{
  "reachable": true,
  "total": 12, "downloading": 2, "seeding": 8, "completed": 9, "paused": 1, "error": 0,
  "total_dlspeed_bytes": 1048576, "total_upspeed_bytes": 20480,
  "total_dlspeed_human": "1.0 MB/s", "total_upspeed_human": "20.0 KB/s",
  "client_name": "qBittorrent", "client_version": "4.5.2", "node": null,
  "message": null
}
```

`client_version` is fetched from `/api/v2/app/version` — best-effort; `null`
if that call fails. `node` is reserved for multi-instance setups and is
currently always `null`. When qBittorrent is unreachable, the response is
`{"reachable": false, "message": "<reason>", ...all counts 0, client_* null}` —
never a `500`.

### `GET /api/v1/torrents/list?state=<downloading|seeding|completed>`

Full torrent queue, optionally filtered by coarse bucket (`state` omitted =
all). Each entry:

```jsonc
{
  "hash": "abc123...", "name": "Some.Movie.2024", "state": "downloading",
  "category": "movies", "progress": 0.42, "progress_percent": 42.0,
  "size_bytes": 4831838208, "size_human": "4.5 GB",
  "downloaded_bytes": 2029255680,
  "dlspeed_bytes": 1048576, "upspeed_bytes": 0,
  "dlspeed_human": "1.0 MB/s", "upspeed_human": "0 B/s",
  "eta_seconds": 2670, "eta_human": "44m",
  "ratio": 0.0, "num_seeds": 12, "num_leechs": 3,
  "added_on_iso": "2026-07-09T18:30:00+00:00"
}
```

`eta_seconds`/`eta_human` are `null` when qBittorrent reports "infinity"
(its `8640000` sentinel). Same unreachable behavior as `/summary`: `{"reachable": false, "count": 0, "torrents": [], "message": "..."}`.

### `GET /api/v1/torrents/ws?state=<downloading|seeding|completed>` (WebSocket)

Push equivalent of `/torrents/list` — same payload shape, sent every
`TORRENTS_WS_INTERVAL` seconds (default 2s) for as long as the client stays
connected. No auth required (same read-only data as the REST endpoint).

### `POST /api/v1/actions/torrents` 🔒

Add a torrent by magnet link or an `http(s)://` URL to a `.torrent` file.
Requires `X-API-Key`. Body:

```jsonc
{ "url": "magnet:?xt=urn:btih:...", "category": "movies", "save_path": null, "paused": false }
```

`category`/`save_path`/`paused` are optional. Response:
`{"ok": true, "message": null}`, or `{"ok": false, "message": "<reason>"}` if
qBittorrent is unreachable or rejects the torrent — never a `500`.

### `POST /api/v1/actions/torrents/file` 🔒

Same as above, but for sharing/uploading a `.torrent` file directly
(`multipart/form-data`: `file` + optional `category`/`save_path`/`paused`
form fields). Rejects non-`.torrent` filenames and files over
`TORRENT_FILE_MAX_MB` (default 10 MB) with a `422`/`413` before ever calling
qBittorrent.

### `POST /api/v1/actions/torrents/pause` · `/resume` · `/delete` 🔒

Control an existing torrent by info hash. Body: `{ "hash": "<info-hash>" }`
(the `hash` field of any `/torrents/list` item). Requires `X-API-Key`.

- **pause** — stops a downloading/seeding torrent (kept in the list, resumable).
- **resume** — starts a paused torrent.
- **delete** — removes the torrent **and its downloaded files on disk**
  (partial or complete) to reclaim space when abandoning a download.

Each returns `{ "ok": true, "message": null }`, or `{ "ok": false, "message":
"<reason>" }` if qBittorrent is unreachable — never a `500`. (Internally
pause/resume map to qBittorrent 5.x's `stop`/`start` API, but the app-facing
names stay `pause`/`resume`.)

### `POST /api/v1/actions/sync-movies` 🔒

Runs the existing `sync-movies` shell script (moves completed downloads from
`torrents/complete` into the movies library — no request body). Then, for
each moved item, removes its qBittorrent entry **metadata-only**
(`deleteFiles=false`, so the moved file is preserved) so completed downloads
don't linger in the torrent list. Items the script *skipped* (already in the
library) are left untouched. Response:

```jsonc
{
  "ok": true, "exit_code": 0, "output": "Moving: Some.Movie.2024\n...\nDone.", "message": null,
  "moved": ["Some.Movie.2024"], "skipped": [], "torrents_removed": 1
}
```

Torrent matching is by `basename(content_path)` (not torrent name — they
differ), restricted to torrents saved under `TORRENTS_COMPLETE_PATH`. If
qBittorrent is unreachable the move still succeeds: `ok` stays `true`,
`torrents_removed` is `0`, and `message` notes cleanup was skipped.
`ok: false` (with a `message`) if the script itself isn't found, fails, or
times out (`SYNC_MOVIES_TIMEOUT`, default 120s) — never a `500`. Manual
trigger only; nothing calls this automatically.

### `GET /api/v1/storage/summary?folder_sizes=<bool, default true>`

Disk usage for each `MONITORED_PATHS` entry, optional per-folder sizes for the
movies/shows/torrents-complete/torrents-incomplete paths, plus SMART health
(`app/services/storage_service.py`).

```jsonc
{
  "disks": [ { "path": "/srv/storage", "exists": true, "total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "percent_used": 67.2, "total_human": "...", "used_human": "...", "free_human": "..." } ],
  "folders": [ { "path": "/srv/storage/media/movies", "exists": true, "size_bytes": 0, "size_human": "...", "entry_count": 4213 } ],
  "smart": { "available": true, "device": "/dev/sda", "healthy": true, "status": "PASSED", "temperature_celsius": 34, "power_on_hours": 8760, "message": null }
}
```

Set `folder_sizes=false` to skip the (slower, `os.walk`-based) folder-size
pass on large libraries. SMART requires `smartmontools` installed and
`SMART_DEVICE` set — otherwise `smart.available: false` with an explanatory
`message` (never a failure of the whole endpoint).

### `GET /api/v1/system/overview`

CPU/memory/swap/uptime/temperature/battery/network, all via `psutil` +
`platform` (`app/services/system_service.py`).

```jsonc
{
  "hostname": "dell-server", "os": "Linux 6.1.0", "kernel": "...", "architecture": "x86_64",
  "uptime_seconds": 123456, "uptime_human": "1d 10h 17m", "boot_time_iso": "...",
  "cpu_percent": 12.3, "cpu_count_logical": 8, "cpu_count_physical": 4,
  "load_average": { "one": 0.42, "five": 0.38, "fifteen": 0.30 },
  "memory": { "total_bytes": 0, "used_bytes": 0, "available_bytes": 0, "percent": 41.0, "total_human": "...", "used_human": "..." },
  "swap": { "total_bytes": 0, "used_bytes": 0, "percent": 0.0, "total_human": "0 B" },
  "temperatures": [ { "label": "coretemp", "current_celsius": 45.0, "high_celsius": 90.0, "critical_celsius": 100.0 } ],
  "battery": null,
  "interfaces": [ { "name": "eth0", "addresses": ["192.168.1.50"] } ]
}
```

`load_average`, `temperatures`, `battery` are simply omitted/`null`/empty when
the kernel/platform doesn't expose them (e.g. no battery on a home server) —
not treated as errors.

### `GET /api/v1/library/summary`

Library counts plus the most recently modified items across both movies and
shows, capped at 10, sized skipped for speed (`app/services/library_service.py`).

```jsonc
{
  "movies_count": 214, "shows_count": 58,
  "movies_root": "/srv/storage/media/movies", "shows_root": "/srv/storage/media/shows",
  "movies_exists": true, "shows_exists": true,
  "recently_added": [ /* MediaItem, see below */ ]
}
```

### `GET /api/v1/library/movies?sizes=<bool, default true>` / `GET /api/v1/library/shows?sizes=<bool, default true>`

Top-level directory listing under `movies_path`/`shows_path` — one item per
folder (or loose media file matching `MEDIA_EXTENSIONS`), sorted by name.

```jsonc
{
  "category": "movies", "root": "/srv/storage/media/movies", "exists": true, "count": 214,
  "items": [ /* MediaItem[] */ ]
}
```

**`MediaItem` shape** (identical across `summary.recently_added`, `movies.items`, `shows.items`):

```jsonc
{
  "name": "Interstellar (2014)",
  "path": "/srv/storage/media/movies/Interstellar (2014)",
  "is_dir": true,
  "size_bytes": 0, "size_human": "0 B",
  "modified_iso": "2026-07-08T12:00:00+00:00",

  "poster_url": "/api/v1/library/artwork?id=a1b2c3d4&size=poster",
  "thumb_url":  "/api/v1/library/artwork?id=a1b2c3d4&size=thumb",
  "year": 2014, "quality": "2160p", "hdr": true,
  "jellyfin_id": "a1b2c3d4"
}
```

- `size_bytes`/`size_human` are `0`/`"0 B"` when `sizes=false` (per-item folder
  sizing is the one genuinely expensive part of this listing — an `os.walk`
  over the whole folder tree). Everything else, including artwork, is
  populated regardless of `sizes`.
- `poster_url`/`thumb_url`/`jellyfin_id` are `null` together when no artwork
  is available (see [Library artwork](#library-artwork) below) — this is a
  normal state, the app shows its placeholder.
- `year`/`quality`/`hdr` are parsed from the folder/file name
  (`app/utils/media_metadata.py`) — always attempted, independent of artwork
  resolution. `year`/`quality` are `null` when nothing matches; `hdr` is
  always a bool (`false` by default).

### `GET /api/v1/library/artwork?id=<jellyfin_id>|path=<url-encoded folder>&size=<poster|thumb, default poster>`

Streams the actual poster/thumbnail bytes referenced by `poster_url`/
`thumb_url` above. You don't hand-build this URL from the app — you just load
the URL the list endpoints already gave you.

- **200** — image bytes, `Content-Type: image/jpeg` (or the source's native
  type), `Cache-Control: public, max-age=86400`, `ETag`. Downscaled
  server-side to ≈500px tall (`poster`) / ≈200px tall (`thumb`) via Pillow —
  never full resolution.
- **304** — when the request's `If-None-Match` matches the current `ETag`.
- **404** — no artwork available for this `id`/`path` (or neither param was
  given). This is the *one* place a failed fetch is an expected, harmless
  outcome — the app falls back to its placeholder. Never `500`.

See [Library artwork](#library-artwork) for how `id=` vs `path=` are chosen
and where the bytes come from.

### `GET /api/v1/services`

Status of each `MONITORED_SERVICES` systemd unit, via `systemctl show`
(`app/services/service_status_service.py`, read-only — no start/stop/restart
in v1).

```jsonc
{
  "available": true,
  "services": [
    { "name": "jellyfin", "active": true, "state": "active", "sub_state": "running", "enabled": true },
    { "name": "qbittorrent-nox", "active": true, "state": "active", "sub_state": "running", "enabled": true }
  ],
  "message": null
}
```

`available: false` (with a `message`) only if `systemctl` itself isn't on
`PATH` (e.g. running this API somewhere non-systemd). Individual units that
don't exist come back with `state: "not-found"`, `active: false` rather than
failing the whole call.

---

## Library artwork

Each `MediaItem` carries `poster_url` / `thumb_url` (or `null`) and
`jellyfin_id` (or `null`), resolved by `app/services/artwork_service.py` and
served by `GET /library/artwork` (documented above). Two sources, ranked:

1. **Jellyfin (preferred)** — enabled by setting both `JELLYFIN_BASE_URL` and
   `JELLYFIN_API_KEY`. The backend fetches Jellyfin's item list once and
   caches a `folder → jellyfin_id` mapping for `JELLYFIN_MAP_TTL` seconds (the
   list endpoints trigger a refresh-if-stale check, but it's a no-op once
   warm — no per-item, per-request Jellyfin calls). Matching, in order:
   - exact filesystem path (works because the API and Jellyfin see the same
     `/srv/storage/media/...` paths on the Dell — also checks the *parent*
     folder of Jellyfin's reported path, since Jellyfin may report the video
     file rather than the folder);
   - clean title + year;
   - clean title alone.

     "Clean title" strips release-junk (resolution, codec, HDR marker,
     source, year) from the folder name, e.g.
     `The.Dark.Knight.Rises.2012.2160p.HDR.BluRay.x265` → `the dark knight
     rises`, so it lines up with Jellyfin's clean title `The Dark Knight
     Rises`.
   - `poster_url` then points at `/library/artwork?id=<jellyfin_id>&size=...`,
     and the artwork endpoint proxies + downscales
     `{JELLYFIN_BASE_URL}/Items/{id}/Images/Primary?maxHeight=...`.
2. **Local files (fallback)** — when there's no Jellyfin match (or Jellyfin
   isn't configured), the backend looks for `poster.jpg` / `poster.png` /
   `poster.webp` / `folder.jpg` / `folder.png` / `cover.jpg` / `cover.png`
   (`ARTWORK_FILENAMES`, in that order) next to the item. Existence is cached
   per-folder for `ARTWORK_LOCAL_TTL` seconds. `poster_url` then points at
   `/library/artwork?path=<folder>&size=...`, and the endpoint reads +
   downscales that file.
3. **Neither available** → `poster_url: null`, `thumb_url: null`,
   `jellyfin_id: null`. The app shows its placeholder — this is a normal
   state, not an error.

Artwork never fails the library listing: if Jellyfin is unreachable or
misconfigured, `/library/summary|movies|shows` still return `200` with
`poster_url: null` (falling back to local files, then `null`). Downscaled
bytes are cached in-memory (`ARTWORK_CACHE_MAX_ITEMS`, LRU) so repeat scrolls
in the app don't re-hit Jellyfin or re-read/re-encode local files.

`year` / `quality` / `hdr` are independent of all of the above — parsed
straight from the folder name and always populated.

---

## Local development (your main laptop)

Requires Python 3.11+.

```bash
cd JigglyPuff-Server

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env          # then edit values as needed

uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs.

> On a non-Dell dev machine the media/download paths won't exist and
> qBittorrent/Jellyfin may be unreachable — that's fine. Those endpoints
> degrade gracefully (`exists=false`, `reachable=false`, `poster_url=null`) so
> you can still develop the app against the API shape. Point `MOVIES_PATH`/
> `SHOWS_PATH` at a local folder (optionally with a `poster.jpg` inside a
> subfolder) and `MONITORED_PATHS` at a local disk to see real data.

---

## Deploying to the Dell

> The systemd unit file is named `media-server-api.service` and the live
> deploy directory on the Dell is `/home/thejus/projects/media-server-api`.
> Those on-disk names are left as-is below so the deploy steps match the
> currently-running service; rename them together with the unit/`WorkingDirectory`
> if you want them to read `jigglypuff-server` too.

1. **Copy the project** to the Dell:

   ```bash
   rsync -av --exclude '.venv' --exclude '.env' \
     JigglyPuff-Server/ thejus@dell:/home/thejus/projects/media-server-api/
   ```

2. **Create the venv & install** on the Dell:

   ```bash
   cd /home/thejus/projects/media-server-api
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env      # set real qBittorrent creds, Jellyfin API key, SMART_DEVICE, etc.
   ```

3. **Install the systemd service:**

   ```bash
   sudo cp media-server-api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now media-server-api
   systemctl status media-server-api
   journalctl -u media-server-api -f
   ```

The API now runs 24/7 on `http://<dell-lan-ip>:8000`.

### Notes on host tooling

- **SMART** (`/storage/summary`) needs `smartmontools` (`sudo apt install smartmontools`)
  and `SMART_DEVICE=/dev/sdX` set. Without root, `smartctl` may return no data —
  either run the service with the needed capability or leave `SMART_DEVICE` empty
  to skip it. All SMART failures degrade to `available=false`.
- **Services** (`/services`) uses `systemctl show`, which works unprivileged for
  status reads.
- **Temperatures/battery** come from `psutil` and are simply omitted if the
  kernel doesn't expose them.
- **Artwork downscaling** needs `Pillow` (in `requirements.txt`). Without it,
  the artwork endpoint still works but serves original-resolution files
  instead of downscaled ones.

---

## Configuration

All config is via environment variables (see `.env.example` for the full list
with comments). Key ones:

| Variable              | Purpose                                             |
|-----------------------|-----------------------------------------------------|
| `ALLOWED_ORIGINS`     | CORS origins for the mobile app (`*` for LAN)       |
| `ACTIONS_API_KEY`     | Shared secret required as `X-API-Key` on `/actions/*` (empty = actions return `503`) |
| `SYNC_MOVIES_SCRIPT_PATH` / `SYNC_MOVIES_TIMEOUT` | `sync-movies` script path + timeout (s) for the trigger endpoint |
| `TORRENT_FILE_MAX_MB` | Max accepted size for an uploaded `.torrent` file   |
| `TORRENTS_WS_INTERVAL`| Seconds between pushes on `/torrents/ws`            |
| `QBITTORRENT_URL`     | qBittorrent Web UI base URL                         |
| `QBITTORRENT_USERNAME` / `QBITTORRENT_PASSWORD` | Web UI credentials       |
| `MOVIES_PATH` / `SHOWS_PATH` | Library roots scanned for `/library/*`       |
| `MONITORED_PATHS`     | Filesystems reported in the storage summary         |
| `MONITORED_SERVICES`  | systemd units reported in `/services`               |
| `SMART_DEVICE`        | Disk for SMART health (empty = disabled)            |
| `JELLYFIN_BASE_URL` / `JELLYFIN_API_KEY` | Jellyfin artwork source (empty = local files / no art) |
| `JELLYFIN_MAP_TTL`    | Seconds to cache the folder→Jellyfin item mapping   |
| `ARTWORK_FILENAMES`   | Local poster filenames to look for, in order        |
| `ARTWORK_POSTER_MAX_HEIGHT` / `ARTWORK_THUMB_MAX_HEIGHT` | Downscale targets (px) |

---

## Extending

`app/api/routes/actions.py` (mounted at `/api/v1/actions`, gated by
`require_api_key` in `app/api/deps.py`) is the first control router — add
torrent and sync-movies live there today. The same pattern applies to future
additions:

- Put write/control logic in **new** service modules (e.g.
  `service_control_service.py`) — leave the read-only modules untouched.
  Remaining extension points are marked with `NOTE (future control
  endpoints)` comments in `qbittorrent_service.py` (pause/resume/delete) and
  `service_status_service.py` (start/stop/restart).
- Add new routes to the existing `actions` router (or a new router mounted
  under `/api/v1/actions`), reusing `require_api_key`.
- Likely additions: pause/resume/delete torrents, restart services, trigger a
  Jellyfin library scan, reboot/shutdown.
