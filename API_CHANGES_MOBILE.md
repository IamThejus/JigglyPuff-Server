# API Changes for the JigglyPuff Mobile App

> What changed in `media-server-api` and what the app needs to do to consume it.
> **All changes are additive and backwards compatible** — nothing was renamed or
> removed, so the app keeps working unchanged until you wire these in.
> All existing routes are still `GET`, no auth, under `/api/v1`. New in this
> round: a `/torrents/ws` WebSocket (also no auth) and a set of `POST
> /actions/*` control endpoints (add / pause / resume / delete torrents,
> trigger sync-movies) that **do** require an `X-API-Key` header — see §6.

---

## TL;DR

| Change | Where | App action |
|---|---|---|
| Poster/thumb URLs on every library item | `LibraryItem` | Load `poster_url` / `thumb_url`, placeholder on `null` |
| Light metadata `year`, `quality`, `hdr` | `LibraryItem` | Show as tags/badges |
| `jellyfin_id` | `LibraryItem` | Store (reserved for future deep link) |
| New image endpoint `/library/artwork` | new route | The app just loads the URLs above — it resolves to this |
| Torrent client identity | `/torrents/summary` | Show `client_name` / `client_version` in subtitle |
| Cleaner movie `name` / `year` (Jellyfin-sourced) | `/library/movies`, `/library/summary` | Nothing required — values just got cleaner; see §4.5 |
| Real-time torrent progress | `GET /torrents/ws` (WebSocket) | Replace polling with a WS connection; see §6 |
| Add torrent (link or shared file) | `POST /actions/torrents`, `/torrents/file` | New buttons; requires `X-API-Key`; see §6 |
| Pause / resume / delete a torrent | `POST /actions/torrents/pause`, `/resume`, `/delete` | Row actions; requires `X-API-Key`; see §6 |
| Trigger sync-movies (move + auto-clear torrents) | `POST /actions/sync-movies` | Button; requires `X-API-Key`; see §6 |

---

## 1. `LibraryItem` — new fields

Appears in **all three** library responses:
- `GET /api/v1/library/summary` → `recently_added[]`
- `GET /api/v1/library/movies` → `items[]`
- `GET /api/v1/library/shows` → `items[]`

```jsonc
{
  // --- existing (unchanged) ---
  "name": "Interstellar (2014)",
  "path": "/srv/storage/media/movies/Interstellar (2014)",
  "is_dir": true,
  "size_bytes": 0,
  "size_human": "0 B",
  "modified_iso": "2026-07-08T12:00:00+00:00",

  // --- NEW ---
  "poster_url": "/api/v1/library/artwork?id=a1b2c3d4&size=poster", // or null
  "thumb_url":  "/api/v1/library/artwork?id=a1b2c3d4&size=thumb",  // or null
  "year": 2014,          // int  | null
  "quality": "2160p",    // "2160p" | "1080p" | "720p" | "480p" | null
  "hdr": true,           // bool (defaults false, never null)
  "jellyfin_id": "a1b2c3d4" // string | null
}
```

**Null handling (important):**
- `poster_url` / `thumb_url` are `null` when no artwork exists → **show the
  existing pink-gradient placeholder**. `null` is a normal state, not an error.
- `year`, `quality`, `jellyfin_id` may each be `null` independently → hide that
  tag/badge.
- `hdr` is always a bool (`false` when not detected) — safe to read directly.

---

## 2. Loading artwork

`poster_url` / `thumb_url` are **relative** URLs starting with `/`. Resolve them
against the app's configured base URL, then load directly:

```
base = "http://<dell-lan-ip>:8000"
imageUrl = base + item.poster_url        // when poster_url != null
```

- Use `thumb_url` (~200px tall) for dense list rows / the recently-added strip.
- Use `poster_url` (~500px tall) for the detail view / larger cards.
- The images are already downscaled server-side — no need to resize on device.
- The endpoint sends `Cache-Control: public, max-age=86400` + `ETag`, so a
  normal `Image.network` / cached image widget will cache and revalidate
  (`304 Not Modified`) automatically. No app-side cache logic needed.

**Error / fallback rule:** on a `null` URL *or* a failed image fetch (e.g.
`404`), fall back to the placeholder gradient. Do **not** treat an image failure
as a "Server Unreachable" state — image loads are the one place a failed fetch
is expected and harmless.

### The endpoint (for reference — the app just loads the URL)

```
GET /api/v1/library/artwork?id=<jellyfin_id>&size=poster|thumb
GET /api/v1/library/artwork?path=<url-encoded path>&size=poster|thumb
```
- `size` defaults to `poster`.
- Returns image bytes (`image/jpeg`/`webp`/`png`) on success.
- Returns `404` when art is missing (never `500`). → placeholder.

You normally don't build this URL yourself — use the `poster_url` / `thumb_url`
the item already gives you (the backend picks `id=` vs `path=` correctly).

---

## 3. Metadata tags

Render the small tags the app already planned:

- `year` → `2014`
- `quality` → `2160p` badge
- `hdr === true` → `HDR` badge

Example row label: `2014 · 2160p · HDR`. Omit any tag whose field is `null`
(or `hdr === false`).

---

## 4. `/torrents/summary` — client identity

Three new nullable fields on the existing summary object:

```jsonc
{
  // ...existing fields unchanged...
  "client_name": "qBittorrent", // string | null
  "client_version": "4.5.2",    // string | null
  "node": null                   // string | null (not used in this setup)
}
```

Use these for the Torrents screen subtitle, e.g. `qBittorrent · v4.5.2`. When
`reachable: false`, all three are `null` (unchanged screen behavior — just show
the generic subtitle).

---

## 4.5. Movie `name` / `year` now come from Jellyfin (cleaner values)

For **movies** (`/library/movies` `items[]` and the movie entries in
`/library/summary` `recently_added[]`), when Jellyfin has the title matched,
`name` and `year` now use **Jellyfin's clean metadata** instead of the raw
filename:

```jsonc
// before: derived from the folder/file name
{ "name": "Ayan.2009.1080p.10bit.BluRay.DTS-6.1.x265.AVK.mkv", "year": 2009 }
// now: Jellyfin's title + production year
{ "name": "Ayan", "year": 2009 }
```

- **No schema change** — same fields, same types. The *values* are just
  nicer. If the app displays `name` directly (it should), titles get cleaner
  with zero app changes.
- **Fallback unchanged**: a movie Jellyfin hasn't scanned/matched yet still
  shows the raw filename-derived `name`/`year` (so freshly added items never
  disappear or go blank).
- **Shows are unaffected** in this round — `/library/shows` `name` is still
  the raw folder name.
- ⚠️ If the app does any **client-side matching/caching keyed on `name`**,
  be aware a movie's `name` can change once Jellyfin finishes scanning it
  (filename → clean title). Key on `path` or `jellyfin_id` if you need a
  stable identifier — those don't change.

---

## 5. Nothing else changed about the existing routes

- No existing field renamed or removed.
- Same routes, same `/api/v1` prefix, same no-auth on everything except the
  new `/actions/*` endpoints (§6).
- `*_human` strings are still pre-formatted — keep displaying them verbatim.
- `/openapi.json` (and `/docs`) reflect all the new fields/endpoints if you
  regenerate client models.

---

## 6. New: real-time torrents + control actions

### `GET /api/v1/torrents/ws` (WebSocket, no auth)

Replaces polling `/torrents/list` for the active-downloads screen. Connect,
then read a `TorrentsList` JSON message (same shape as the REST response)
every ~2s until you disconnect. Same optional `?state=downloading|seeding|completed`
filter as the REST endpoint. Reconnect on drop — there's no resume/backfill,
each message is a full snapshot.

### Adding a torrent — needs `X-API-Key`

The app needs a configured API key (same one set in the server's
`ACTIONS_API_KEY`) sent as the `X-API-Key` header on these two:

- **Magnet link / URL** (e.g. user pastes a magnet link, or shares a link
  into the app): `POST /api/v1/actions/torrents`, JSON body
  `{"url": "magnet:?xt=..."}`.
- **Shared `.torrent` file** (share sheet → app): `POST
  /api/v1/actions/torrents/file`, `multipart/form-data` with the file under
  the `file` field.

Both return `{"ok": true, "message": null}` on success, or `{"ok": false,
"message": "<reason>"}` — show the message as a toast/error, don't treat it
as a hard failure state (qBittorrent being briefly unreachable is a normal
condition, same as elsewhere in this API).

### Pause / resume / delete a torrent — needs `X-API-Key`

Control a torrent that's already in the list (e.g. a download you started but
no longer want). All three take the same JSON body — the `hash` from any
`/torrents/list` (or `/torrents/ws`) item:

- `POST /api/v1/actions/torrents/pause` — `{"hash": "<hash>"}` → stops it
  (stays in the list, resumable).
- `POST /api/v1/actions/torrents/resume` — `{"hash": "<hash>"}` → restarts it.
- `POST /api/v1/actions/torrents/delete` — `{"hash": "<hash>"}` → removes the
  torrent **and deletes its files on disk** (partial or finished). Use this
  for "cancel this download and clean up." Consider a confirmation prompt in
  the app since this is destructive.

Each returns `{"ok": true, "message": null}` or `{"ok": false, "message":
"<reason>"}` (qBittorrent unreachable, etc.) — same soft-fail handling as the
add endpoints. Good fit for swipe actions / a long-press menu on each torrent
row.

### Sync movies — needs `X-API-Key`

`POST /api/v1/actions/sync-movies`, no body. Runs the server-side script that
moves completed downloads into the movies library. Manual only — nothing
triggers it automatically, so surface it as an explicit button (e.g. on the
Torrents or Library screen) rather than firing it in the background.

After moving files, it also **removes the qBittorrent entry** for each moved
item (metadata only — the moved movie file is preserved), so completed
downloads stop lingering in the torrent list once they're in the library.
Items already present in the library are skipped and left untouched.

Response:

```jsonc
{
  "ok": true, "exit_code": 0, "output": "<script stdout>", "message": null,
  "moved": ["Ted (2012) [1080p]", "Lucy.2014.mkv"], // basenames moved this run
  "skipped": ["Vanilla Sky"],                       // already in library
  "torrents_removed": 2                             // entries cleared for moved items
}
```

Show e.g. "Moved 2, removed 2 torrents" from `moved`/`torrents_removed`
instead of parsing `output`. If qBittorrent is unreachable, the move still
succeeds — `ok` stays `true`, `torrents_removed` is `0`, and `message`
explains cleanup was skipped.

### Where to store the API key

Treat it like any other server config the app already has (base URL) —
a settings field, not hardcoded. If it's wrong/missing, `/actions/*` calls
return `401`; if the server has none configured, `503`. Both are safe to
surface as "control actions disabled — check settings."

---

## 7. Suggested app-side change (minimal)

Swap the hard-coded placeholder for a cached network image with the gradient as
the error/`null` fallback:

```dart
// pseudo-Flutter
final url = item.posterUrl;                 // may be null
if (url == null) {
  return PosterPlaceholder();               // existing gradient
}
return Image.network(
  '$baseUrl$url',
  fit: BoxFit.cover,
  errorBuilder: (_, __, ___) => PosterPlaceholder(),
  // loadingBuilder: show gradient/shimmer while loading
);
```

That plus the `year` / `quality` / `hdr` tags is the whole app-side change.
