# 03 — Stage 2: server and browser interface

Serve the stage 1 index as a browsable, streamable collection.

## Backend — FastAPI on port 8090

| Route | Purpose |
|---|---|
| `GET /api/files` | Paged list. Filters: `q`, `ext`, `favorite`, `min_dur`, `max_dur`. Sorts: name, duration, size. |
| `GET /api/files/{hash}` | Detail. Includes every alias path, metadata, favorite state, tags. |
| `GET /api/files/{hash}/peaks` | Waveform peaks. Computed and cached on first call. |
| `GET /api/files/{hash}/stream` | Audio bytes. Supports HTTP range requests. |
| `PUT /api/files/{hash}/favorite` | Mark favorite. |
| `DELETE /api/files/{hash}/favorite` | Unmark. |
| `GET /api/dupes` | Duplicated hashes. Scoped to within-root by default; `?within_root=false` counts every alias. |
| `GET /api/stats` | Counts, total size, wasted bytes, format breakdown. |

**Streaming.** Serve the first alias that still exists on disk. WAV, MP3, and
M4A stream directly from the file with range support. AIF is transcoded to WAV
by piping through ffmpeg, because browser support for AIFF is uneven. Transcoded
responses are not range-seekable; that is acceptable for a first version.

Never accept a path from the client. The client sends a hash; the server looks
up the path. This is the whole defence against path traversal, so it must hold
on every route.

**Favorites attach to the hash.** Marking any alias marks the sound. This is the
main reason the schema is hash-first.

**Duplicate counting must ignore mirrored roots.** `audio-library/` is a
deliberate working copy of `compost/`, so counting every alias reports 3,429 of
3,451 sounds as duplicated. That is 89% noise and hides the real redundancy.
`/api/dupes` therefore counts only copies that repeat inside a single root,
which gives 378 groups. `?within_root=false` restores the raw count.
`/api/stats` keeps the raw count on purpose, because it measures the footprint
on disk rather than what can be cleaned up.

**Project bundles are not reclaimable.** Of the 33 GB that within-root scoping
reports, about 29 GB is audio inside `.logicx` project bundles and only 3.9 GB
is ordinary samples. A Logic project reads its media from that exact path, and
those projects live only in the read-only originals, so removing one corrupts
the project permanently.

`/api/dupes` therefore leaves bundle copies out, which takes the cleanup view
from 378 groups and 33 GB down to 286 groups and 3.9 GB. The response reports
what it withheld in `excluded_bundle_groups` and `excluded_bundle_bytes`, and
the interface states it above the list rather than dropping it silently.

The filter is on copies, not on whole sounds. A bounce stored twice in ordinary
folders and once more inside a project still appears, because the two loose
copies are real redundancy; its `wasted_bytes` counts only those two. Every path
of a listed group comes back in `entries` with `in_bundle` and `deletable`, and
the interface marks the untouchable ones **in a project**.
`?include_bundles=true` lists the withheld groups too, with `deletable: false`
on every bundle path.

Nothing here deletes audio, and the server exposes no route that could. The only
`DELETE` it accepts unmarks a favorite. `test_no_route_can_remove_an_audio_file`
in `tests/test_server.py` is where a new one would show up.

**Seeking a transcoded stream.** AIF is piped through ffmpeg, so the response
has no length and no byte offsets: `Accept-Ranges: none`. About 1,180 paths are
AIF. `FileSummary.transcoded` carries this on every list row, not only on the
detail, because the player bar is fed from list rows. The waveform draws with
`data-seekable="false"` and a not-allowed cursor, the detail view prints a line
saying the file plays from the start, and a click on the waveform puts the same
sentence in the player bar. A click that silently did nothing was the bug.

**Spans.** `GET /api/files/{hash}/spans` reads the `span` table from
[04-segmentation.md](04-segmentation.md). Stage 2 never writes to it, so the
route answers 200 with an empty list, which is not the same as a 404: it says
the sound exists and has no labels yet. `?method=` narrows to one classifier.
`schema.sql` is applied on every connection and every statement in it is
`CREATE ... IF NOT EXISTS`, so an index written before the table existed picks
it up on open.

## Frontend — Next.js on port 3100

Three views.

**List.** Virtualised table of the collection. Columns: name, duration, format,
size, alias count, favorite toggle. Search box filters on filename. Clicking a
row loads it into the player without leaving the list.

**Detail.** One sound. Waveform canvas, transport controls, full metadata, and
every alias path that resolves to this hash. The alias list is what makes
duplication visible: a file with three paths shows all three.

**Playlist.** The current filtered set, played in order, with continuous
playback across tracks and prefetch of the next track's peaks.

Draw waveforms on `<canvas>` from the peaks endpoint rather than decoding audio
in the browser. Decoding a 200 MB WAV client-side will stall the tab. The canvas
component must accept a span overlay, because stage 3 colour-codes it.

Use `wavesurfer.js` only if its peak-array input path is used directly. Do not
let it fetch and decode whole files.

## Configuration

`config.toml` holds roots, database path, ports, and bind address. Bind
`0.0.0.0` so the Tailscale address reaches it. The Tailscale CLI is not on
`PATH`; the app does not need it, it only needs to bind broadly.

## Acceptance

- `make dev` starts both servers.
- The list view loads 4,600 rows without stalling.
- Audio plays, seeks, and advances to the next track.
- A favorite set on one alias shows on every alias of that hash.
- Browser tests cover: load list, search, play, favorite, view dupes.

## Browser tests

Playwright, not Cypress. `cd frontend && npm run test:e2e`, with
`npm run test:e2e:install` once per machine to fetch Chromium. The config is
`frontend/playwright.config.ts` and the specs are in `frontend/e2e/`.

Two projects, because the interface has two jobs that need different data.

**mock** runs against mock mode on port 3101, which Playwright starts itself.
The fixture comes from a fixed seed, so exact counts can be asserted. It covers
the list rendering and virtualising, search, a favourite surviving a reload, the
stream URL carrying a hash and nothing else, the waveform canvas painting real
pixels, the bundle guard, and the refusal to seek a transcoded stream.

**live** runs against the stack on port 3100 and the real index. It covers the
facts only real data shows, and only reads.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [02-hash-and-db.md](02-hash-and-db.md)
- **next**: [04-segmentation.md](04-segmentation.md)
