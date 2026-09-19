# audio-browser

A tool for listening through a personal sound library once and deciding what
each sound is for.

The library is not a catalogue to browse. It is a queue to answer. One sound
fills the screen and loops. There are two answers: take it into the project on
the bench, or discard it. There is no third answer, and no surface anywhere puts
a sound back into the undecided pile. Discard is reversible, so being decisive
is cheap and being indecisive is the problem the tool exists to remove.

## The model

A sound is its bytes. The BLAKE3 digest of a file's bytes is the identity of the
sound, and a path is only an alias that points at a digest. Two files with
identical bytes are one sound with two names.

Every decision attaches to the digest. Answering one copy answers every copy,
and a file that is moved or renamed keeps its answer. The client sends a hash to
every route and never sends a path; the server reads the path out of the
database.

A **project** is a JSON file in `projects/`, one per project, holding a list of
hashes. The file is the truth. SQLite indexes those files so the board can be
drawn without opening every one, and when the two disagree the files win.

## The views

The interface is a Next.js app. It is used from a phone over Tailscale, so it is
built for one thumb.

| Path | What it is |
|---|---|
| `/` | Swipe. One undecided sound, looping, with its waveform. Take it or discard it. This is the front door. |
| `/search` | Matches for a typed name, and nothing else. An empty query shows an empty view. |
| `/decided` | The record of what was answered: taken into a project, or discarded. Filter by answer, project, and name. |
| `/board` | The columns, their caps, and the projects in them. Commit, abandon, revive. |
| `/sounds/{hash}` | One sound: waveform, measured silence, and the spans one classifier found. |

There is no playlist, no duplicates view, no favourites and no standalone lists.
A star meant "decide later" and a list that is not a project is a pile with no
exit. Both are ways to spend time without deciding. The `favorite`, `list` and
`list_member` tables still hold their rows: removing the routes was the
decision, and destroying data would be a second one.

The duplicates report survives as a command and a route, not as a view.

## Ports

| Port | What listens |
|---|---|
| 8090 | The FastAPI server, bound to `0.0.0.0` so a Tailscale address reaches it |
| 3100 | The Next.js app. It forwards `/api/*` to 8090, so the browser only ever talks to 3100 |
| 3101, 3102, 3103 | Mock servers that Playwright starts for itself |

`NEXT_PUBLIC_MOCK=1` drops the forward and serves generated fixtures from
`frontend/app/api/` instead. Never start the app on 3100 that way: the fixtures
look like sounds, and swiping them decides nothing.

There is no authentication. Anyone who can reach port 8090 can read the library
and answer sounds, so the tailnet is the security perimeter.

## Install

Python 3.12 or newer, managed with `uv`. `ffmpeg` and `ffprobe` must be on PATH.

```bash
uv sync
cp config.toml.example config.toml   # then edit the roots
cd frontend && npm install
```

The classifiers need TensorFlow, PyTorch, transformers and Silero VAD, close to
3 GB of wheels. Nothing else needs them, so they are an optional extra:
`uv sync --extra segment`.

## Configure

`config.toml` says where the index lives, which trees to index, where the server
listens, and what the caps are. `config.toml.example` documents every key.

```toml
db = "audio-browser.db"

[[roots]]
name = "compost"
path = "../compost"

[server]
host = "0.0.0.0"
port = 8090
frontend_port = 3100   # only used to build the default CORS origins

[projects]
dir = "projects"
cap = 1            # projects one column may hold
encumbrance = 16   # sounds past which a project is marked as carrying too much
```

`path` is resolved through symlinks before the walk, so `../compost` is stored
as its real target.

**The roots are read-only.** The scan and the server open audio files for
reading and nothing else. `compost/` is `chmod a-w` on disk, which turns any
mistake into an immediate `EACCES`. `dedupe --apply` is the single exception and
is run by hand.

## Commands

```bash
uv run audio-browser scan       # walk the roots, hash, probe, record
uv run audio-browser serve      # the HTTP API on 0.0.0.0:8090
uv run audio-browser stats      # totals per root, extension, and codec
uv run audio-browser search kick        # full-text search over filenames
uv run audio-browser peaks --limit 50   # cache waveform peaks
uv run audio-browser silence            # measure dead air
uv run audio-browser segment yamnet     # label spans of speech, music, other
uv run audio-browser bakeoff            # where the classifiers agree and differ
uv run audio-browser projects           # read the project files
uv run audio-browser dupes              # duplicate groups and the verdict
uv run audio-browser dedupe --root audio-library   # dry run unless --apply
```

`--config PATH` and `--db PATH` work on every command. `--help` lists the rest.

The `Makefile` wraps the ones used most:

```bash
make install        # uv sync
make test           # the offline unit tests
make typecheck      # mypy
make check          # both
make serve          # the HTTP API
make scan           # index every configured root
make segment METHOD=yamnet
make test-e2e       # the browser tests
```

There is deliberately no `make dedupe-apply`. Deleting files is a decision, so
it is typed out in full.

## The HTTP API

FastAPI, with interactive documentation at `/docs`.

| Route | Purpose |
|---|---|
| `GET /api/health` | liveness, plus the blob and alias counts behind it |
| `GET /api/swipe` | the next undecided sound, with its silence, its spans and the project on the bench |
| `GET /api/files` | one page of the library, one row per sound |
| `GET /api/files/{hash}` | one sound, its aliases, its tags, and the projects holding it |
| `GET /api/files/{hash}/peaks` | waveform peaks, computed on the first call and cached |
| `GET /api/files/{hash}/silence` | where a sound is silent, so playback can skip it |
| `GET /api/files/{hash}/spans` | labelled regions; `?method=yamnet` narrows to one classifier |
| `GET /api/files/{hash}/stream` | audio bytes, with HTTP range support |
| `PUT` / `DELETE /api/files/{hash}/deleted` | discard a sound, or restore it |
| `POST /api/bulk` | discard or restore many hashes in one transaction |
| `GET /api/triage` | how much of the library has been answered |
| `GET /api/board` | the columns, their caps, the encumbrance threshold, and what is blocked |
| `GET /api/projects` | every project, with its column and its counts |
| `POST /api/projects` | start one in `stored` |
| `GET` / `PATCH /api/projects/{id}` | the document; rename or edit notes |
| `POST /api/projects/{id}/commit` | freeze this column's artifact and advance |
| `POST /api/projects/{id}/abandon` | leave the board and free the slot, keeping the file |
| `POST /api/projects/{id}/revive` | come back to the column it left |
| `PUT` / `DELETE /api/projects/{id}/sounds/{hash}` | take a sound in, or take it out |
| `GET /api/dupes` | redundancy a cleanup could act on, most bytes first |
| `GET /api/stats` | counts, total size, wasted bytes, format breakdown |

**No route removes an audio file.** Every `DELETE` the server accepts removes a
row: a soft delete, or one entry from a project document. Two tests hold that
promise. One compares the `DELETE` routes against a written list of what each
removes. The other drives every state-changing route and then compares both
audio roots file by file and size by size.

**One request per sound.** `GET /api/swipe` answers with the sound, its silent
gaps, its YAMNet spans, the project a take would go into, and the counts. The
swipe view uses all of it. Three round trips over a tailnet were felt; one is
not.

**The client draws what the server reports.** The caps, whether a column is over
its cap, and the encumbrance threshold all come from `GET /api/board`. The
client has its own copies of those numbers only for mock mode. A client drawing
its own idea of a rule can show a column as fine while the server refuses every
write to it.

**The order of the queue is by hash.** Arbitrary matters: a digest has nothing
to do with the folder a file sits in, so a pass does not spend an hour inside
one pack. Fixed matters more: the same call answers the same sound until that
sound is answered, so a reload resumes instead of reshuffling.

## Silence

`audio-browser silence` measures every gap down to 0.4 seconds and stores it.
The floor is applied when the measurement is read, so it is a setting rather
than a property of the data. The interface uses 2 seconds: measured over the
whole library, that recovers 10.4 of the 11.5 available hours, while a shorter
floor jumps over musical rests and makes the player jitter.

Playback skips those gaps, so a five minute stem with forty seconds of sound
takes forty seconds. A scrub into a gap is an instruction and is left alone. An
AIF is transcoded as it streams and carries `Accept-Ranges: none`, so it cannot
be seeked and cannot be skipped through; the interface says so rather than
looking broken.

## Spans

`segment` splits a sound into spans and labels each one `speech`, `music` or
`other`, so the waveform can be tinted. Three classifiers exist and each writes
rows tagged with its own `method`.

| Method | What it is | Device |
|---|---|---|
| `yamnet` | YAMNet over AudioSet's 521 classes | CPU |
| `vad` | Silero VAD for speech edges, AST for music | GPU |
| `clap` | CLAP scored against written descriptions | GPU |

The interface draws YAMNet and names it in the request. `bakeoff` put `vad` and
`yamnet` in agreement 82.9% of the time while `clap` agreed with neither, so
tinting all three over each other would say nothing about any of them.
`agent_notes/audio-browser/06-bakeoff-results.md` holds the comparison.

A run is restartable: every sound gets a `segment_run` row as soon as it
finishes, success or failure, and a restart skips whatever already has one.
Nothing is cached to disk. Discarded sounds are skipped unless
`--include-discarded` is passed.

## Projects and the board

Two columns are real. `stored` is where swiping puts sounds. Committing out of
it freezes the project's sound set and moves the project to `collage`, where the
arrangement is built. `enrich` is in the document schema, so a file may name it,
but it is not a column: nothing commits into it and it holds no slot.

Each column holds `cap` projects, one by default. Going over a cap is possible,
takes an explicit override, and leaves the column visibly over its limit until
the count comes down.

**The board deadlocks, on purpose.** `stored` commits and frees the lane; a new
project is born there; it cannot commit because `collage` is full; and `collage`
cannot commit either, because no column follows it. `GET /api/board` says so in
`blocked`, `blocks` and `detail` rather than leaving it to be found by pressing
a button that will always be refused.

**Abandon is the only way out.** It frees a slot without promoting anything and
keeps the file. **Revive** brings a project back to the column it left, paying
for the slot again.

**Encumbrance** is a mark, not a limit. Past the threshold a project is marked
in every view that shows it. Adding still works, and the mark clears itself when
the count comes back down.

## Deduplication

`dedupe` removes paths that hold a sound another path in the same root already
holds. It is a dry run unless `--apply` is given, and it always needs `--root`:
a default root would eventually be applied to the wrong tree.

Five rules decide what may go, and all of them must hold.

1. **One root at a time.** The two trees mirror each other on purpose, so a twin
   in the other root never makes a path here redundant.
2. **Never a bundle path.** A file inside a `.logicx` directory is that
   project's own media, read from that exact path.
3. **Never beside a project file.** REAPER resolves media by bare filename, so
   audio sharing a directory with a `.rpp`, `.rpp-bak` or `.als` is
   load-bearing. A directory that cannot be read counts as holding a project:
   missing evidence must never read as "safe to delete".
4. **Keep the shallowest survivor.** Ties are broken alphabetically. Protected
   copies survive on top of it, so a sound always keeps one freely-browsable
   path.
5. **Never reduce a sound to zero copies in the root.**

Every path is checked to lie under the named root at plan time and again
immediately before the unlink, through symlinks. A plan holding one bad path
deletes nothing at all. Each removed path is written to the `deletion` table
before its `alias` row is dropped, so a sound can say "also seen at X, deleted
on Y" instead of letting the path vanish.

## Tests

```bash
uv run pytest tests/ -v   # offline; generates its own WAV fixtures
uv run mypy               # type check
cd frontend && npm run test:e2e
```

No test reads the real library. The API tests build a two-root fixture in a
temporary directory and drive it through Starlette's test client, so they never
open a port. Tests that need `ffmpeg` skip themselves when it is missing.

`test_server.py` walks every hash route with hostile values — path traversal in
several encodings, an absolute path, SQL, and a 64-character non-hex string —
and asserts none of them gets past the hash check.

Playwright drives a real browser in five projects, defined in
`frontend/playwright.config.ts`:

| Project | Against |
|---|---|
| `mock` | mock mode on 3101, from a fixed seed, so counts and names repeat |
| `mobile` | the same server under an iPhone descriptor: WebKit, touch, 393 by 852 |
| `live` | the real stack on 3100. Read-only, for facts only real data shows |
| `cap1` | mock mode on 3102 with the column cap turned down to 1 |
| `capbad` | mock mode on 3103 with the cap mistyped, which must tighten the board |

## Layout

| Path | What it holds |
|---|---|
| `src/audio_browser/` | scanning, hashing, probing, peaks, silence, dedupe, reports |
| `src/audio_browser/server/` | the FastAPI app, its queries, its models, streaming |
| `src/audio_browser/projects/` | the project document model and its store |
| `src/audio_browser/segment/` | the three classifiers and the pure span builder |
| `src/audio_browser/schema.sql` | the whole schema, applied on every connection |
| `frontend/app/` | the views and the mock API routes |
| `frontend/lib/` | the API client, the project model, the pure silence rules |
| `frontend/e2e/` | the browser tests |
| `schemas/` | JSON Schema generated from `frontend/lib/project.ts` by `npm run schema` |
| `projects/` | one JSON file per project. The truth; SQLite is a cache of it |

The project model is written once, in Zod, in `frontend/lib/project.ts`.
`npm run schema` emits JSON Schema from it into `schemas/`, and Python validates
every project file against that. `frontend/scripts/check-schema.py` puts the
same documents to both languages and fails on any disagreement, so the two
cannot drift.
