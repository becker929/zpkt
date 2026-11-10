# The music bot and the booth (design)

A design, not yet built, written 1 November 2026. Friends mention a Bluesky account with an idea. A short piece is
made in Live on this Mac, and the reply is a vertical video of it. Replying under a piece makes the next version.

It follows the Room World room bot (`~/world2/bot`, its README): intake and a like within seconds, a quick Haiku
ack, one slow job at a time, checks before anything is built, and its own macOS user. This document is mostly about
the one part the room bot doesn't have: the **booth**, the interface between the bot and Live.

## The two bots side by side

| | Room bot | Music bot |
|---|---|---|
| What a request becomes | a room: WGSL + sound emitters | a **score**: parts, notes, palette instruments, a mix |
| Free check before the slow work | `check_shader` (naga), Chrome WebGPU | `POST /v1/check` (schema, palette, ranges, cost) |
| Where it is made | Room World's Worker, over HTTP with the bot's token | the booth, over loopback HTTP with the bot's token |
| The slow part | Chrome renders a video, ~3 s | Live builds and exports, ~40-90 s |
| Shared resource | none (Chrome per job) | **one Live, which is also Anthony's instrument** |
| Checks after | ms per frame | measurements by ears (silence, peaks, loudness, balance) |
| Reply | 8 s MP4 of the room | MP4: the render's audio over a picture made from the score |

## The boundary

```
 roombot (macOS user)                      anthonybecker (GUI session)
 ┌──────────────────────────┐   loopback   ┌───────────────────────────────┐   LOM :16619   ┌─────────┐
 │ bot/  (Node)             │   HTTP +     │ contrib/booth  (Python, uv)       │  (AbletonLive  │ Live 12 │
 │ intake ▸ like ▸ ack      │   token      │ check ▸ queue ▸ compile ▸     │   MCP Remote   │ Suite   │
 │ compose (Claude) ▸ fix   │ ───────────► │ build ▸ export ▸ measure ▸    │ ─────────────► │         │
 │ reply (video upload)     │ ◄─────────── │ encode ▸ files                │   + menus/AX   │         │
 │ secrets: Bluesky, Claude,│  127.0.0.1:  │ uses hands, ears; Live lease; │                └─────────┘
 │ booth token              │  8794        │ ntfy on a surprise            │
 └──────────────────────────┘              └───────────────────────────────┘
```

- **The bot runs as `roombot`, the room bot's macOS user.** One bot user on the Mac, two programs in it, each with
  its own LaunchAgent: the room bot (`me.anthonybecker.roombot`, from world2) and the music bot
  (`me.anthonybecker.musicbot`, from zpkt `bot/`). The music bot's code is root-owned in `/usr/local/musicbot`;
  its state and secrets are in `/Users/roombot/_agent_scratch/music-bot/`. It holds the music bot's own Bluesky app
  password (a separate account from the room bot's), its Claude workspace key and the booth token. Nothing of
  Anthony's: his home folder is 700 since the room bot's setup, and the booth's files come back over HTTP.
  The trade: roombot's Chrome renders strangers' shaders, so a compromise there reaches the music bot's secrets too.
  The booth's rule below bounds what that buys: a booth token can queue scores and nothing else.
- **The booth runs as Anthony**, because Live does: one license, one GUI session, the virtual display. It is a small
  HTTP service on `127.0.0.1:8794` (clear of the harness's 8787/8788, studio dev 8790/8791, Room World 8970 and
  artworld's 8960s). Every request carries `Authorization: Bearer zb1_…`; the token is in Anthony's Keychain
  (`zpkt-booth-token`) and copied once into the bot's secrets by `setup-mac.sh --secrets`.
- **HTTP, not a shared spool folder.** It has the same shape as `world.mjs` (one client class, JSON in and out), the
  bot can check a draft synchronously, the files come back over the same socket so no folder needs shared
  permissions between the two users, and the tests can run a fake booth the way they run `fake-bsky.mjs`.

### The one rule: the booth takes a score, never code

The Remote Script runs any Python it is sent inside Live, as Anthony (`hands live exec`). So nothing a stranger
wrote, and nothing Claude wrote for a stranger, may ever reach `LiveClient.run`. The booth's only input is a score:
JSON checked against `lib/contracts/score.schema.json`. Every LOM call the booth makes comes from its own compiler,
in git. In particular:

- Instruments, effects and controls are **palette ids**, looked up in a table the booth owns. No browser paths, file
  paths or device names come from the score.
- Numbers are bounded by the schema and again by the palette (pitch range per instrument, macro 0..1).
- Text (title, credits) is metadata only. It never names a track, a set or a file; the booth names those
  `booth_<job id>`, and the job id is its own (`[a-z0-9]{12}`).
- The booth never opens, saves or touches a set without the `booth_` prefix. Anthony's sets and library are
  not in its reach (`set_prefixes` for the booth is `["booth_"]` only).

## The score (the contract)

A pydantic model in `contrib/booth`, exported to `lib/contracts/score.schema.json` by the same generator as the other
contracts, so a drift fails the contract tests. The bot's composer (Claude, structured output) writes it directly.

Plain shapes for Claude's structured outputs: lists of objects with fixed keys, no maps keyed by the model's own
names, no tuples, extra keys refused. Two full examples are in `contrib/booth/palettes/examples/`.

```json
{
  "score": 1, "palette": "2026-11", "title": "clockwork in F minor", "bpm": 120, "key": "F minor",
  "feel": { "swing": 0.1, "humanize_ms": 5, "velocity_jitter": 6, "seed": 7 },
  "parts": [
    { "id": "drums", "instrument": "drums.clockwork", "gain_db": 0, "pan": 0, "room": 0.15, "echo": 0 },
    { "id": "bass", "instrument": "bass.sub_mellow", "gain_db": -2, "macros": [{ "name": "drive", "value": 0.6 }] },
    { "id": "keys", "instrument": "keys.upright", "gain_db": -6, "pan": 0.15, "room": 0.45, "echo": 0.2 }
  ],
  "patterns": [
    { "id": "beat", "part": "drums", "bars": 1, "notes": [{ "p": 36, "t": 0, "d": 0.25, "v": 110 }, { "p": 38, "t": 1, "d": 0.25, "v": 96 }] },
    { "id": "line", "part": "bass", "bars": 2, "notes": [{ "p": 29, "t": 0.5, "d": 0.4, "v": 96 }] },
    { "id": "chords", "part": "keys", "bars": 2, "notes": [{ "p": 53, "t": 0, "d": 3.5, "v": 72 }] }
  ],
  "song": [
    { "bars": 4, "play": [{ "part": "keys", "pattern": "chords" }] },
    { "bars": 8, "play": [{ "part": "keys", "pattern": "chords" }, { "part": "drums", "pattern": "beat" }, { "part": "bass", "pattern": "line" }] }
  ],
  "mix": { "room": "hall", "echo": "dotted_eighth" }
}
```

- **Notes** are `{p, t, d, v}`: pitch, start beat within the pattern, length in beats, velocity. 4/4 only. Patterns
  repeat to fill their song section and are cut at its end, so a model writes a few dozen notes, not thousands, and a
  revision ("double the hats in the second half") is a small edit a person could read.
- **Feel** is applied by the booth's compiler, seeded, so swing and humanizing come out the same every time and the
  model doesn't have to fake them note by note (SH001's seeded humanizing, moved into trusted code).
- **Samples.** A part may play an uploaded sample instead of an instrument, by the id the booth gave it: as audio
  clips in the arrangement (warped to the song's tempo or not), or in a Simpler that patterns play whole or in
  slices (`contrib/booth/README.md`, "Samples"). The id is checked against the booth's own store, and the path that
  reaches Live is the booth's.
- **The mix** is gain, pan, two sends and the instrument's named macros. The returns and the master chain are fixed:
  two palette returns (a room and an echo, each with a few named settings) and a master the booth owns (SH001's
  EQ Eight high-pass, Glue Compressor and true-peak Limiter). Friends shape the music; the booth keeps it safe to play.

| Limit | Value | Why |
|---|---|---|
| Length | 4-64 bars, at most 60 s of audio | Live's export costs ~13 s plus ~0.1 s per audio second |
| Parts | at most 8 | each is a track load (~1 s) |
| Notes | at most 2,000 after repeats | `add_new_notes` calls stay well under the 12 s transport timeout |
| BPM | 60-180 | |
| Pitches | each instrument's range in the palette | out of range is an error, not a clamp |
| Macros | 0..1, palette-named only | each maps linearly between two display values of one device parameter |

### The palette

`contrib/booth/palettes/<version>.toml`, curated by Anthony, one file a month (`"palette": "2026-11"`). A palette is never
edited once a score has used it, so an old score renders the same. Each entry:

```toml
[instrument."bass.sub_mellow"]
role = "bass"
load = ["sounds", "Bass", "Sub Mellow.adg"]        # browser root, folder, item: for liveops.load_item
fx = ["Saturator"]
set = { 1 = { "Type" = "Bass Shaper", "Drive" = "10 dB", "Output" = "-7 dB" } }
trim = -8.5                                         # the starting volume that balanced it in SH001
range = [24, 55]
about = "a round sub bass; the drive macro makes it carry on a phone speaker"
macros = { drive = { device = 1, param = "Drive", lo = "0 dB", hi = "16 dB" } }
```

The booth serves one palette to the composer (`palette` in its `config.toml`, else `palette.SERVED`) and renders
any it has, so a new month's file changes nothing until the booth is switched to it. `booth survey --listen` loads,
plays and measures each instrument in Live first (`<version>.survey.json`); 2026-12 adds forty to 2026-11's eleven.

`about` and `role` go to the composer; `load` and the macro mappings never leave the booth. The first palette is
Live 12 Suite's Core Library only, the presets SH001 was made with: nothing purchased, nothing of Anthony's, nothing
in iCloud (reading iCloud from Live raised a prompt and froze its main thread on 2026-10-15). VEC2 can join later,
copied into the template's project, once Anthony has decided about its license in public posts. A seams kit (Core
Library found sounds on a Drum Rack, as in SH001) gives section changes their marks.

## The API

All JSON. Errors are `{error, message}` with a stable `error` code, as in Room World.

| | Request | Answer |
|---|---|---|
| `GET /v1/guide` | | the palette as the composer sees it (ids, roles, ranges, `about`, macros), the score rules and two example scores. The bot caches it in Claude's system prompt, like `shader_guide`. |
| `POST /v1/check` | `{score}` | `{ok, errors: [{path, code, message}], warnings, estimate: {audio_s, render_s, notes}}`. Saves nothing and never touches Live, so the composer can iterate free, up to 3 rounds. |
| `POST /v1/jobs` | `{key, score, parent?, want: {video: {size: [1080, 1920]}, stems: false}}` | `202 {job, state, position, eta_s}`. `key` is the bot's idempotency key (the mention's URI plus a version): the same key answers the same job, so a bot that crashed mid-request never renders twice. `429 queue_full`, `503 closed {reason, retry_in_s}`. |
| `GET /v1/jobs/{job}` | | `{state, stage, position, eta_s, timings, measure, files, error}` |
| `GET /v1/jobs/{job}/files/{name}` | | `render.m4a`, `video.mp4`, `still.jpg`, `score.json`, `measure.json` (and `stems/*.m4a` if asked) |
| `DELETE /v1/jobs/{job}` | | cancels a queued job; a running one finishes |
| `GET /v1/status` | | `{open, reason, queue, live: {ok, front, engine}, today: {jobs, live_s}}` |
| `POST /v1/samples` | the audio file as the body (WAV, AIFF, FLAC, MP3; 20 MB, 60 s) | `201` (or `200`: the same bytes before) `{sample, seconds, channels, sample_rate, peak_db, lufs, onsets_s, format}`. `403 samples_off`, `413 too_large`, `415 bad_format`, `400 unreadable`, `too_long`, `too_short`, `silent`. |
| `GET /v1/samples/{id}` | | the same measurements |

Job states: `queued → building → rendering → measuring → done`, or `failed {stage, code, retryable}`, or `held`
(the booth stopped itself on a surprise, below). The bot polls a job every 5 s; nothing calls back into the bot.

## Inside the booth: one job at a time

1. **Lease.** A job starts only when the booth is open, inside its hours, nothing else used the LOM in the last 5
   minutes (`session.last_lom_connection`, not counting the booth's own last job), and **one of the booth's own sets
   is in front of Live**. That last rule is the lease. Anthony gives the booth Live by leaving it on
   `booth_template`, and takes it back by opening any set of his. The booth never opens a set over one of his, so it
   can never close his work or raise "Save changes?" on it. The harness's Claude Code jobs open their own sets, so
   they take Live the same way. While the booth may not start, jobs wait in the queue; only a booth that is closed
   (by Anthony, or by a hold) answers `503 closed`.
2. **Set.** `copy_set("booth_template", "booth_<job>")`, then `open_set`. The template is a Live 12-native set
   (never an older one: the "save as a new file" dialog) with one empty MIDI track `p1` (Live won't delete a set's
   last track, so jobs reuse it as their first part), and the two returns and Main's chain in place. `booth
   template` makes it once, watched.
3. **Build.** Tracks named `p1`..`p8`, instruments from the palette (`liveops.load_item`, then a read-back of the
   track's devices), settings and macros in display units (`liveops.setp`), one arrangement clip per track with
   `add_new_notes` 400 notes to a call (then the clip's note count read back), the mixer and sends, the returns'
   settings. Each LOM call short, each read back in a separate call. Arrangement automation, if a later score version adds it, is
   written into the `.als` with `als.py` before the set opens, since the LOM can't write it.
4. **Render.** `liveops.export` (menu clicks and accessibility, no keystrokes, so a stray system prompt can't eat
   them), staged in liveops' own folder (the Save panel's Where popup can't reach the booth's) and moved to the job,
   then `audio.check_audio` (readable, the right length, not silent). **Loudness, in Live:** if the render is more
   than 2 LU under -14 LUFS, Main's Limiter Input Gain goes up by the shortfall (whole dB, at most +24) and it exports
   once more. The first two real renders came out at -21.6 and -20.7 LUFS without it; the lullaby with it, -14.2.
5. **Measure.** Integrated LUFS (pyloudnorm, as ears), true peak (4x oversampled), each section's loudness (v8's
   "flat and smooshed" lesson) and the 180 Hz phone model. These go back in `measure.json` with flags and a plain
   sentence each: `silent` (which holds the job: Live's audio engine), `clipping`, `too_quiet`, `no_contrast`,
   `lost_on_phone`. Per-part stems are for later.
6. **Encode.** `render.m4a` (AAC 256k) and `video.mp4`: the audio over a 1080x1920 picture drawn from the score
   (a piano roll per part in its colour, a moving playhead, the title, tempo and key), drawn with Pillow and
   encoded by ffmpeg in the booth.
   No browser is involved, so no Web Audio question arises (`docs/sound.md`).
7. **Close.** The booth opens `booth_template` again (`open_set` saves the job's set first, so Live never asks) and
   deletes the job's `.als`. The score plus the palette version is the
   record: any piece can be rebuilt. Files stay 30 days under `~/_agent_scratch/booth/jobs/<job>/`.

Measured on the first runs (2026-11-01, three parts, about 33 s of audio): open 3-5 s, build 44-47 s (browser loads
dominate, ~15 s a part), export 15-16 s, the loudness pass 18 s when needed, close and encode 4 s. About 70 s a
piece, 90 s with the loudness pass, so 60 renders a day is about 1.5 hours of Live.

### On a surprise, stop

Anthony on 2026-10-06: "Hands is still young." The booth is an unattended chain, so it is the most cautious part of
the system:

- `session.check` runs before and after every step. A dialog, an unexpected set in front, a LOM timeout, a silent or
  wrong-length render, Live's audio engine off: the job becomes `held`, **the booth closes itself**, and ntfy tells
  Anthony with the stage and what was wrong. It never retries a Live step and never takes the next job.
- `booth open` (CLI, as Anthony) reopens it after he has looked. `booth close` closes it any time, for example while
  he works in Live; queued jobs wait.
- A held job is not lost: the bot sees `held`, tells the friend there was a hiccup on the bot's side, and the job
  re-runs from the start when the booth opens.
- Failures that are the score's fault (it passed `check` but the compiler refused it) are `failed` with
  `retryable: false`, and never close the booth.

## The bot side

`bot/` in zpkt, Node, installed into roombot by `sudo bot/setup-mac.sh` (it refuses to run until world2's
setup has made the user). The room bot's pieces are carried over as they are where they fit (`bsky.mjs`, `richtext.mjs`,
`store.mjs`, `limits.mjs`, `ack.mjs`, `secrets.mjs`, `setup-mac.sh`, `fake-bsky.mjs`). `world.mjs` becomes
`booth.mjs`: a `Booth` class with `guide()`, `check(score)`, `submit(key, score, parent)`, `job(id)`, `file(id, name)`.

```
intake (2 s) ─► like ─► limits ─► ack (Haiku): piece / revise / chat / decline / ignore
                                        │
                                        ▼
compose (Claude, high effort) ─► booth check ─► fix (≤3) ─► booth job ─► poll ─► measure flags? ─► one revision round
                                                                                     │
                                                         reply with video ◄─ upload ◄┘
```

What friends can do:

- **Start a piece.** Mention the bot with an idea. Version 1 is a new score.
- **Revise it.** Reply under one of the bot's pieces ("slower, and let the bass breathe"). The composer gets the
  parent score and the instruction and writes the next version; the reply goes in the same thread. Anyone in the
  thread can revise, so a thread is a piece being made together, one version per reply.
- **Remix.** Quote a piece and mention the bot. The new score starts from the quoted one and credits it.

The bot keeps each version's score and parent in `bot.db`. A later phase can also write them as records in the bot's
own Bluesky repo (`me.anthonybecker.zpkt.piece`, with a strong ref to the parent), the same way Room World keeps
rooms in owners' repos, so the lineage of every piece is public and rebuildable.

One render-side fix round is allowed per version, when `measure.json` flags a real problem (a part you can't hear,
no contrast between sections). Check rounds are free; render rounds cost Live time.

### Limits (starting values, all in `config.json`)

| Setting | Default | |
|---|---|---|
| `dryRun`, `open`, `allow` | `true`, `false`, Anthony's handle | as in the room bot; `open` stays false (below) |
| `piecesPerUserPerDay`, `revisionsPerUserPerDay` | 2, 6 | |
| `rendersPerDay` | 60 | about an hour of Live a day |
| `dollarsPerDay` | 15 | composer + acks; hard stop at 1.25x |
| `queueMax` (booth) | 10 | past it the ack says to try later |
| `boothHours` (booth) | `["10:00-23:00"]` local | Anthony's to set; the booth's own setting, not the bot's |

## Tests

- **Booth:** pytest with hands' `MockTransport` for the compiler (a score becomes exactly these LOM calls, chunked,
  each read back), schema and palette tests, and contract tests against `score.schema.json`. A guard test per
  surprise (dialog, wrong set, silent render) proves the booth holds and closes.
- **Bot:** `node contrib/bot/test.mjs` against `fake-bsky.mjs` and a fake booth (`fake-booth.mjs`: check answers, jobs that
  pass, fail, hold), with a scripted brain, so nothing is posted and Live isn't needed.
- **End to end:** a supervised session with the real Live: five scores through the booth, timings and
  measurements recorded, then the eval (twenty requests, real Claude, booth live, a report page with every video).

## Rollout

1. Booth and `check` first, driven by hand from a shell; five real renders watched.
2. The eval.
3. Bot in dry run with `open: false`, replies to `outbox/`.
4. Live for the allow list: Anthony, then friends by handle.
5. **Recommended: stay friends-only.** Live is Anthony's instrument and the rig needs a person when it stops. `open`
   exists, but the booth's hours, queue and hold rule assume a small circle.

## Decisions for Anthony

- **The palette.** Which instruments and kits friends get. VEC2 in public posts is a license question for him.
- **Booth hours**, and whether the booth closes itself whenever he opens one of his own sets.
- **The account** (e.g. `tunes.anthonybecker.me`) and the friends' handles for the allow list.
- **Covers.** Room World has no copyright surface; music does. Suggested default: style and mood yes, recreating a
  specific song's melody or lyrics no (the ack declines).
- **Where pieces go afterwards.** Whether friends' pieces may surface in his library or The Wasteland, or stay in
  the booth's folder.
