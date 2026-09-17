# audio-browser

An index of a personal audio collection, keyed by content.

The BLAKE3 digest of a file's bytes is the identity of a sound. A path is only
an alias that points at a digest. Two files with identical bytes are one sound
with two names. Favorites and tags attach to the digest, so marking one copy
marks every copy, and a file that moves keeps its marks.

Stage 1 is the index and its command line. Stage 2 is an HTTP API that serves
the index: list, detail, waveform peaks, audio streaming, and favorites.

## Install

Python 3.12 or newer, managed with `uv`. `ffmpeg` and `ffprobe` must be on
PATH.

```bash
uv sync
cp config.toml.example config.toml   # then edit the roots
```

The classifiers in stage 3 need extra packages — TensorFlow, PyTorch,
transformers and Silero VAD, close to 3 GB of wheels. Nothing else in the
project needs them, so they are an optional extra:

```bash
uv sync --extra segment
```

## Configure

`config.toml` lists the trees to index. Nothing is hardcoded.

```toml
db = "audio-browser.db"

[[roots]]
name = "compost"
path = "../compost"
```

`name` is what reports call the tree. `path` is resolved through symlinks
before the walk, so `../compost` is stored as its real target.

An optional `[server]` table sets where the API listens. Every key has a
default, so the table can be left out.

```toml
[server]
host = "0.0.0.0"       # bind broadly: this is what a Tailscale address reaches
port = 8090
frontend_port = 3100   # only used to build the default CORS origins
```

`cors_origins` and `cors_origin_regex` override the defaults, which allow any
host on the frontend port. There is no authentication. Anyone who can reach the
port can read the collection and change favorites, so the tailnet is the
security perimeter.

**The roots are read-only to the scan and the server.** The scan opens files for
reading. It never writes, moves, or deletes anything under a root. So does the
server: audio files are opened `"rb"`, and ffmpeg only ever reads them.
`compost/` is `chmod a-w` on disk, which turns any mistake here into an
immediate `EACCES`.

`dedupe --apply` is the one exception, and it is a hand-run cleanup, not part of
any automatic path. See [Deduplication](#deduplication).

## Commands

```bash
uv run audio-browser scan     # walk the roots, hash, probe, record
uv run audio-browser dupes    # duplicate groups and the redundancy verdict
uv run audio-browser stats    # totals per root, extension, and codec
uv run audio-browser peaks --limit 50   # cache waveform peaks for 50 blobs
uv run audio-browser search kick        # full-text search over filenames
uv run audio-browser serve              # the HTTP API on 0.0.0.0:8090
uv run audio-browser dedupe --root audio-library   # dry run; see below
uv run audio-browser segment yamnet     # label spans of speech, music, other
uv run audio-browser bakeoff            # where the classifiers agree and differ
```

Useful flags:

| Flag | Effect |
|---|---|
| `--config PATH` | use a config file other than `./config.toml` |
| `--db PATH` | write the index somewhere other than the configured path |
| `scan --root NAME` | index one root instead of all of them |
| `scan --no-probe` | hash only; skip `ffprobe` |
| `scan --reprobe` | probe every blob again |
| `scan --no-prune` | keep aliases whose file has disappeared |
| `scan --workers N` | thread pool size, default 8 |
| `dupes --limit N` | how many groups to print; `0` for none, `-1` for all |
| `dupes --subject A --against B` | which root to test for redundancy, and against what |
| `serve --host H --port N` | override the bind address for one run |
| `dedupe --root NAME` | the one root to deduplicate; required, no default |
| `dedupe --apply` | actually delete. Without it the command only reports. |
| `dedupe --plan-out PATH` | write the full proposed deletion list to a file |
| `dedupe --examples N` | how many example lines to print, default 10 |
| `segment METHOD` | `yamnet`, `vad` or `clap`; see "Segmentation" below |
| `segment --limit N` | stop after N sounds |
| `segment --max-duration S` | skip sounds longer than S seconds |
| `segment --include-discarded` | also classify discarded sounds; off by default |
| `segment --force` | redo sounds that already have a run record |
| `bakeoff --method M` | include one method; repeatable. Default: every method present |
| `bakeoff --examples N` | how many disputed sounds to show per pair, default 5 |

## Deduplication

`dedupe` removes paths that hold a sound another path in the same root already
holds. It is a dry run unless `--apply` is given, and it always needs `--root`.
There is no default root, because a default would eventually be applied to the
wrong tree.

Five rules decide what may go. All of them must hold.

1. **One root at a time.** Copies are counted inside a single root. The two
   trees mirror each other on purpose, so a twin in the other root never makes
   a path here redundant.
2. **Never a bundle path.** A file inside a `.logicx` directory is that
   project's own media. Logic reads it from that exact path.
3. **Never beside a project file.** REAPER resolves media by bare filename next
   to the `.rpp`, so any audio sharing a directory with a `.rpp`, `.rpp-bak`, or
   `.als` is load-bearing. This is a filesystem question, not an index one: the
   index holds no `.rpp` rows, so each candidate directory is scanned once and
   the answer cached. A directory that cannot be read counts as holding a
   project, because missing evidence must never read as "safe to delete".
4. **Keep the shallowest survivor.** Among the copies that may be deleted, the
   one with the fewest path separators survives, ties broken alphabetically.
   Protected copies survive on top of it, so a sound always keeps at least one
   freely-browsable path and not only a copy buried inside a project folder.
5. **Never reduce a sound to zero copies in the root.** When every copy of a
   sound is protected, nothing is deleted for it. The command reports how many
   sounds that was.

Every path is checked to lie under the root that was named, at plan time and
again immediately before the unlink, including through symlinks. A plan holding
one bad path deletes nothing at all: validation runs to completion before the
first file goes. `--apply` also refuses a root whose directory is not writable,
which is what `compost/` is.

Each removed path is written to the `deletion` table before its `alias` row is
dropped. That record has no foreign key to `blob`, so a later scan that prunes
an orphan blob cannot erase it. `GET /api/files/{hash}` returns those rows as
`deleted_sightings`, so a sound can say "also seen at X, deleted on Y" instead
of letting the path vanish without a trace.

```bash
uv run audio-browser dedupe --root audio-library --plan-out /tmp/dedupe-plan.txt
uv run audio-browser dedupe --root audio-library --apply   # after reading the plan
```

Every line in the plan file that does not start with `#` is a path to delete, so
the file reads as a report and also feeds a command.

## What counts as audio

`.wav`, `.aif`, `.aiff`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.opus`. Everything
else is ignored, including REAPER projects and peak caches, Ableton sets, MIDI,
presets, and images. Matching is by extension only, so audio stored inside a
Logic bundle (`.logicx/Media/Audio Files/`) is indexed like any other file.

Files whose name starts with `._` are skipped. Those are macOS AppleDouble
sidecars: a few kilobytes of resource-fork metadata wearing an audio extension.

## How a scan works

1. Walk each root. Directory symlinks are not followed, so a loop cannot trap
   the walk.
2. Resolve each file through symlinks and `stat` it. Skip files already
   recorded under the same root with the same size and mtime.
3. Hash the rest with BLAKE3 in 1 MB chunks, in a thread pool.
4. Write the `blob` row, then the `alias` row. Only the main thread writes to
   SQLite, so there is no lock contention.
5. Probe new blobs with `ffprobe` for duration, sample rate, channels, and
   codec. One probe per blob, not per path, because probing is the slow part.
6. Prune aliases whose file is gone, then blobs that lost every alias. A
   favorited or tagged blob is kept even with no alias.

The scan is restartable. `journal_mode=WAL` and `synchronous=NORMAL` are on, so
a crash costs at most the unflushed batch. Re-running a scan over an unchanged
tree does no hashing and finishes in seconds.

Pruning is skipped for a root that yielded no audio files. An unmounted volume
looks the same as a deleted tree, and throwing away the index for a tree that
is merely offline is worse than keeping stale rows.

## Tables

| Table | Holds |
|---|---|
| `blob` | one row per unique byte-string: hash, size, duration, sample rate, channels, codec, peaks |
| `alias` | one row per path: which hash it points at, its root, filename, extension, mtime |
| `favorite` | hashes the user marked |
| `tag` | hash-to-name pairs |
| `deletion` | one row per path `dedupe` removed: hash, path, root, time, reason |
| `soft_delete` | hashes the user discarded; no file is involved |
| `list` | a named collection of sounds |
| `list_member` | which hashes are in which list, and in what order |
| `span` | labelled regions of a sound, one row per classifier per region |
| `segment_run` | one row per sound per classifier: status, span count, audio seconds, wall seconds, peak memory |
| `alias_fts` | FTS5 index over filename and path, kept in sync by triggers |

`deletion` and `soft_delete` sound alike and mean different things. `deletion`
records a path that `dedupe --apply` removed from disk; it is history, and it
outlives the blob row. `soft_delete` records a judgement, that the user does not
want this sound; the bytes stay exactly where they are and restore is a `DELETE`
of the row. Both can hold the same hash at once: a redundant copy can be swept
from disk while the sound is still wanted, and a sound can be discarded while
every copy of it survives.

`alias.seen_at` records when that alias row was last written, not when the file
was last observed. An unchanged file is skipped without a write, so its
`seen_at` stays where it was.

The full schema is in `src/audio_browser/schema.sql`.

## Peaks

`peaks` holds 1,000 buckets, 2 bytes each: the minimum then the maximum sample
in that bucket, as signed 8-bit values scaled down from 16-bit. That is 2,000
bytes per sound, so a collection of 5,000 sounds costs about 10 MB.

Peaks are computed on request, never during a scan. Decoding thousands of files
up front takes hours and proves nothing about the index. ffmpeg decodes to mono
22.05 kHz signed 16-bit and the result is reduced to buckets as it streams, so a
long DJ mix does not land in memory.

## The HTTP API

`uv run audio-browser serve` starts FastAPI on `0.0.0.0:8090`. Interactive
documentation is at `/docs`.

| Route | Purpose |
|---|---|
| `GET /api/health` | liveness, plus the blob and alias counts behind it |
| `GET /api/files` | one page of the collection, one row per sound |
| `GET /api/files/{hash}` | one sound, with every alias, every path `dedupe` removed, its tags, and its favorite state |
| `GET /api/files/{hash}/peaks` | waveform peaks, computed on the first call and cached |
| `GET /api/files/{hash}/spans` | labelled regions of the sound; empty until stage 3 writes them |
| `GET /api/files/{hash}/stream` | audio bytes, with HTTP range support |
| `PUT /api/files/{hash}/favorite` | mark a sound; optional JSON body `{"note": "..."}` |
| `DELETE /api/files/{hash}/favorite` | unmark it |
| `PUT /api/files/{hash}/deleted` | discard a sound; optional JSON body `{"note": "..."}` |
| `DELETE /api/files/{hash}/deleted` | restore it |
| `GET /api/lists` | every list, with member count, duration, and size |
| `POST /api/lists` | make a list; body `{"name": "..."}`; 409 if the name is taken |
| `GET /api/lists/{id}` | one list and a page of its members, in play order |
| `PATCH /api/lists/{id}` | rename it |
| `DELETE /api/lists/{id}` | remove it and its memberships |
| `PUT /api/lists/{id}/members/{hash}` | put one sound at the end of the list |
| `DELETE /api/lists/{id}/members/{hash}` | take one sound out of it |
| `POST /api/bulk` | one action over many hashes, in one transaction |
| `GET /api/triage` | how much of the collection has been decided |
| `GET /api/dupes` | redundancy a cleanup could act on, most bytes first |
| `GET /api/stats` | counts, total size, wasted bytes, format breakdown |

Every DELETE the server accepts removes a row: a favorite, a soft delete, a
list, or a membership. There is no route that removes an audio file, and there
is not going to be one. The duplicates view exists to make redundancy visible;
which copy to keep is decided by ear, by hand.

`GET /api/files` takes `q` (a filename substring), `ext` (repeat it or
comma-separate: `?ext=wav,mp3`), `favorite`, `deleted`, `min_dur`, `max_dur`,
`sort` (`name`, `duration`, `size`, `aliases`), `order`, `limit`, and `offset`.

`deleted` is one of `false` (the default), `true`, or `any`. Discarding a sound
is a request to stop seeing it, so the default view hides it without the client
asking. `?deleted=true` is the discarded pile, where restore puts things back.

A row in the list is a sound, not a path. Its `filename`, `path`, and `root`
come from the primary alias, the lowest-numbered path pointing at that hash;
`alias_count` says how many paths there are in total. Filters match against any
alias, so a file found under two names is found under either one.

### The client never sends a path

Every route that names a sound takes a hash. The hash is matched against
`^[0-9a-f]{64}$` before anything else happens, so a value that reaches SQL is 64
hexadecimal characters and cannot be a path, a wildcard, or a query. The path is
then read out of the database. There is no route that accepts, parses, or joins
a client-supplied path, so a traversal attempt has nothing to escape from. A
request for `/api/files/../../etc/passwd` is a routing miss; a request for
`/api/files/' OR 1=1 --` is a 400.

### Streaming

The server serves the first alias of the hash that still exists on disk.
Aliases go stale between scans, so the lowest-numbered one may be gone; every
alias holds the same bytes, so any survivor is the same sound. When no alias
survives, the route returns 404.

WAV, MP3, M4A, FLAC, OGG, and Opus go out as they are, with `Accept-Ranges:
bytes`. A `Range` request comes back as 206 with a `Content-Range`, read from
the file at an offset, so seeking inside a 687 MB file costs a 1 KB read.

AIFF is transcoded to WAV by piping through ffmpeg, because browser support for
AIFF is uneven. A transcoded body has no known length, so it cannot be seeked:
the response says `Accept-Ranges: none` and carries `X-Transcoded-From: .aif`.
`playable` and `transcoded` on the detail route say up front which of the two a
sound will be.

### Triage

Listening to the whole collection once is the real work, and triage is the
machinery for getting through it. A sound counts as triaged once a decision
exists about it: starred, discarded, or filed into at least one list. Nothing
else counts. `GET /api/triage` reports `triaged` over `total` with a percentage,
plus the split by state.

The three counts in the split overlap on purpose and do not sum to `triaged`. A
sound that is both starred and in a list is one sound done, counted once by
`triaged` and once by each of `starred` and `listed`.

Every decision keys on the hash, so it applies to every copy of that sound at
once. A path is never sent by the client and never accepted by a triage route.

**Soft delete removes nothing.** `PUT /api/files/{hash}/deleted` writes one row
and stops there. The audio is not read, not moved, and not removed; every alias
of the hash is still on disk afterwards, which is what makes restore free. The
sound still streams while it is discarded. Sweeping discarded sounds off the
disk is a later decision and is not built.

**Bulk is all or nothing.** `POST /api/bulk` takes
`{"hashes": [...], "action": ..., "list_id": ...}` where the action is one of
`star`, `unstar`, `delete`, `restore`, `add_to_list`, or `remove_from_list`. At
most 1,000 hashes per request. The batch runs inside one `BEGIN IMMEDIATE`
transaction and commits together or rolls back together: a batch of a thousand
that half applied could not be told from one that fully applied, and no one
would repair it by hand.

Each hash in the batch passes the same `^[0-9a-f]{64}$` gate a path parameter
does, so a batch is not a back door; one malformed value refuses the whole
request. Hashes the index does not know are skipped rather than refused,
because a client's selection can be older than the last rescan. The response
counts what happened — `requested`, `unique`, `matched`, `changed`,
`unchanged`, `skipped` — instead of a result per hash.

### Duplicates, and what may not be removed

`GET /api/dupes` answers one question: what could a cleanup actually remove?
Two rules narrow it to that.

**Mirrored roots do not count.** `audio-library/` is a deliberate working copy
of `compost/`, so counting every alias reports 3,429 of 3,451 sounds as
duplicated. `/api/dupes` counts only copies that repeat inside a single root,
which gives 378 groups. `?within_root=false` restores the raw count.
`/api/stats` keeps the raw count on purpose, because it measures the footprint
on disk rather than what can be cleaned up.

**Audio inside a DAW project bundle does not count.** A Logic project is a
directory ending in `.logicx`, and its recorded media lives inside it. The
project reads each file from that exact path, and those projects exist only in
the read-only originals, so removing one corrupts a project permanently. Of the
33 GB that within-root scoping reports, 29 GB is bundle internals and only
3.9 GB is ordinary samples. `/api/dupes` therefore leaves bundle copies out,
which gives 286 groups. The response says how much was withheld, in
`excluded_bundle_groups` and `excluded_bundle_bytes`.

The filter is on copies, not on whole sounds. A bounce stored twice in ordinary
folders and once inside a project still appears; its `copies` and
`wasted_bytes` count only the two loose copies. Every path of a listed group is
returned in `entries` with `in_bundle` and `deletable`, so the interface can
mark the untouchable ones rather than hide them. `?include_bundles=true` lists
the withheld groups as well, with `deletable: false` on every bundle path.

### Spans

`GET /api/files/{hash}/spans` reads the `span` table, which stage 3 fills with
labelled regions from one or more classifiers. A sound nothing has run over
answers 200 with an empty list. That is not the same as a 404: it says the sound
exists and has no labels yet. `?method=yamnet` narrows to one classifier, which
is how two classifiers are compared over the same sound.

The table is created by `schema.sql`, which is applied on every connection. Each
statement in it is `CREATE ... IF NOT EXISTS`, so an index written before the
table existed picks it up when the server next opens it.

### Peaks

Peaks are computed on the first request for a hash and written to `blob.peaks`.
The response carries `cached`, which is false on the call that did the work. A
27-minute WAV takes about two seconds to decode the first time and under two
milliseconds after that. One decode runs per hash at a time, so a list view
asking for ten waveforms at once does not start ten ffmpeg processes on the same
file.

### Requests and threads

Routes are plain functions, so Starlette runs them in its worker pool and each
worker holds its own SQLite connection. WAL mode lets those readers run while
another thread writes a favorite or a peaks blob.

A blob with no aliases left is not listed or streamed: there is nothing to play.
The scan keeps such a blob when it is favorited or tagged, so the mark survives
until a later scan finds the file again.

## Segmentation

`segment` splits a sound into spans and labels each one `speech`, `music` or
`other`, so the waveform can colour-code it. Three classifiers exist and all
three can run over the same sound. Each writes rows tagged with its own
`method`, so the interface switches between them and the `bakeoff` command
measures where they disagree. `agent_notes/audio-browser/06-bakeoff-results.md`
holds the comparison and the recommendation.

| Method | What it is | Frame | Device |
|---|---|---|---|
| `yamnet` | YAMNet over AudioSet's 521 classes | 0.48 s | CPU |
| `vad` | Silero VAD for speech edges, AST for music | true boundaries for speech, 5.12 s for music | GPU |
| `clap` | CLAP scored against written descriptions | 2.5 s | GPU |

`vad` stands in for pyannote, which the plan named. `pyannote/segmentation-3.0`
is gated: an anonymous request for its config answers 401, and reaching it needs
a Hugging Face account, an accepted licence and a token. Silero VAD fills the
same role — a purpose-built detector that emits true speech boundaries — is MIT
licensed, and ships its weights inside its wheel.

A run is restartable. Every sound gets a `segment_run` row as soon as it
finishes, success or failure, and a restart skips whatever already has one.
Failures are recorded and the run continues; one file ffmpeg cannot open is not
a reason to abandon the rest. Force a retry with `--force`.

Discarded sounds are skipped. The collection is triaged, and classifying
rejected material would spend hours on sounds no view will ever show. Pass
`--include-discarded` to override that.

Nothing is cached to disk. Audio is decoded through ffmpeg in blocks, fed to the
classifier and dropped. The longest recording here is close to twelve hours,
which would be 2.7 GB held at once as 16 kHz float samples.

### How frames become spans

`src/audio_browser/segment/spans.py` is the pure core. It loads no model, opens
no file and touches no database, and it holds every decision about turning frame
labels into drawable spans:

1. **Smooth.** A categorical median filter over a five-frame window removes lone
   disagreeing frames. Ties keep the frame's own label.
2. **Merge.** Runs of frames sharing a label become one span. Confidence is the
   mean of the frames; `detail` is their commonest fine-grained class, so a
   stretch of music can say "drum kit".
3. **Absorb.** A span under 0.5 seconds is folded into its longer neighbour
   rather than deleted, so the timeline stays gap-free. A sound shorter than the
   floor keeps its single span.

### Models and where they are cached

YAMNet comes from TensorFlow Hub and unpacks under
`~/.cache/audio-browser/tfhub`. The other two come from Hugging Face and land in
`~/.cache/huggingface`. Together they are about 3 GB. Nothing downloads until a
classifier is actually constructed.

## Tests

```bash
uv run pytest tests/ -v   # offline; generates its own WAV fixtures
uv run mypy               # type check
```

No test reads the real collection. Tests that need `ffmpeg` or `ffprobe` skip
themselves when the tool is missing. The API tests build a two-root fixture in a
temporary directory and drive it through Starlette's test client, so they never
open a port.

`test_server.py` walks every hash route with a list of hostile values — path
traversal in several encodings, an absolute path, SQL, and a 64-character
non-hex string — and asserts that none of them gets past the hash check.

Two tests hold the promise that no route removes audio.
`test_no_route_can_remove_an_audio_file` compares the application's DELETE
routes against a written list of what each one removes, so adding a DELETE
route is a decision rather than a detail.
`test_every_mutating_route_leaves_every_file_on_disk` then drives every
state-changing route in turn and compares both audio roots, file by file and
size by size, before and after. Reading the source proves nothing if a helper
three calls down opens a file for writing, so the suite checks the disk itself.

`test_triage.py` covers soft delete, lists, bulk edit, and the counter. Its
transaction test installs a trigger that refuses one hash out of three, then
asserts that the other two rows never landed.

### Browser tests

```bash
cd frontend
npm run test:e2e:install   # once per machine: fetches Chromium
npm run test:e2e           # both projects
```

Playwright drives a real browser. Two projects, in `frontend/playwright.config.ts`:

**mock** runs against mock mode on port 3101, which Playwright starts itself.
The fixture collection comes from a fixed seed, so counts and names are the same
every run. It covers list rendering and virtualisation, search, favourites
surviving a reload, the stream URL carrying a hash and nothing else, the
waveform canvas actually painting pixels, the duplicates view's bundle guard,
and the refusal to seek a transcoded stream. It writes nothing that outlives the
dev server.

**live** runs against the stack on port 3100, backed by the real index. It
checks the facts only real data shows: a sound stored 30 times inside Logic
project bundles, a sound mirrored once per root, and the 29 GB the cleanup view
withholds. Every test in it only reads.

## Reading the `dupes` verdict

`dupes` ends with a redundancy check: how many blobs under one root also exist
under another. When the untwinned count is zero, every byte of the first tree is
already present in the second, so the first tree is a redundant copy.

The command reports the number and stops. It never deletes anything. Deleting a
tree is a separate decision made by a person.
