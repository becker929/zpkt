# contrib/booth

The booth takes scores from the Bluesky music bot and renders them in Live on this Mac. It is the only way the bot
reaches Live. The design is `docs/design/bluesky-bot.md`.

A score is data: palette instruments, notes, a mix (`src/booth/score.py`, and `lib/contracts/score.schema.json`
generated from it). The booth never runs code it was sent. Every LOM call comes from its own compiler.

## Layout

| File | What |
|---|---|
| `score.py` | the score model and its limits |
| `palettes/2026-11.toml` | what a score may name: Core Library instruments (SH001's), two returns, Main's chain |
| `palettes/2026-12.toml` | 2026-11's eleven and forty more Core Library instruments; not served yet |
| `palettes/<v>.survey.json` | what `booth survey` read from Live: devices, drum pads, rack macros, loudness |
| `palettes/examples/` | two scores, also shown to the composer |
| `samples.py` | uploaded audio: magic bytes, ffmpeg to WAV at 44.1 kHz, kept as `samples/<hash>.wav`, measured |
| `check.py` | `check(raw)`: errors with paths, warnings, an estimate; never touches Live |
| `compile.py` | a checked score becomes a `Plan`: absolute notes, the booth's track names, mixer values in dB |
| `live.py` | a `Plan` into Live, one checked step at a time; also `make_template` and `survey` |
| `gui.py` | SH001's keystroke-free helpers (`hands/scripts/rummage/liveops.py`), loaded from there |
| `measure.py`, `video.py` | measurements and flags; the piano-roll still, the MP4 and the M4A |
| `jobs.py`, `runner.py` | the job table, the lease (`Gate`) and the hold-and-close rule |
| `server.py`, `cli.py` | the HTTP API on 127.0.0.1:8794, and Anthony's controls |

Everything the booth keeps is in `~/_agent_scratch/booth/` (`BOOTH_HOME`): `booth.db`, `jobs/<id>/`, the sets in
`sets/booth Project/`, `samples/`, and an optional `config.toml` (`port`, `hours`, `queue_max`, `quiet_s`, `palette`,
`samples`).

## The first runs (watched, in this order)

```bash
cd contrib/booth
uv run booth check palettes/examples/clockwork.json      # no Live
uv run booth plan palettes/examples/clockwork.json       # no Live: the tracks, note counts and mixer
uv run booth template                                    # once: makes booth_template from File > New Live Set
uv run booth survey                                      # each instrument once: devices and drum pad names
uv run booth run palettes/examples/clockwork.json        # one job, in this shell, with booth_template in front
uv run booth token --new                                 # the bot's token, into the Keychain
uv run booth open
uv run booth serve                                       # in tmux, like the harness
```

First runs (2026-11-01): the template, the survey (drum pad names now in the guide) and three renders, about 70 s
each, 90 s with the loudness pass. `booth run` is for a person watching: it skips the open flag, hours and quiet
time, but still needs a `booth_` set in front. `booth serve` starts a job only while a `booth_` set is in front of Live. Opening any other set takes
Live back. `booth close` stops new jobs. A held job closes the booth until `booth open`.

## Palettes

A score names its palette (`"palette": "2026-11"`), and check, compile and jobs take any palette the booth has, so an
old score renders the same after a new month's file lands. `GET /v1/guide`, and so the composer, gets one palette:
`palette` in `config.toml` if set, else `palette.SERVED`. `GET /v1/guide?palette=2026-12` shows another, to try the
bot on it first. A new palette goes in like this, each step watched:

```bash
uv run booth close "palette survey"                         # only when status shows nothing running or queued
uv run booth survey --palette 2026-12 --listen --only a,b   # ~10 at a time: load, play, export, measure
uv run booth open                                            # straight after each batch
```

`--listen` plays a phrase on each instrument at 0 dB with Main's chain off in the survey's copy of the template, and
writes its loudness to the survey file. A new instrument's `trim` brings it to the median of the old ones (their
`lufs` plus `trim`). Then switch: `palette = "2026-12"` in `config.toml`, and restart `booth serve`.

## Samples

Audio a friend shared with the bot (a video's soundtrack, an audio link) can play in a score. The bot fetches and
converts it, then sends the file as the body of `POST /v1/samples` (WAV, AIFF, FLAC or MP3 by its first bytes, at
most 20 MB and 60 s). The booth converts it with ffmpeg, its demuxer forced to that format, to 24-bit WAV at 44.1 kHz,
keeps it as `samples/<id>.wav` (the id is the first 16 hex digits of the upload's SHA-256, so the same bytes answer
the same id), and measures it: seconds, peak, loudness, and where its hits start. `GET /v1/samples/<id>` answers the
same. A score names a sample only by that id; the path Live gets is the booth's own.

A part has `instrument` or `sample`, never both:

```json
{ "id": "found", "gain_db": -4, "room": 0.2,
  "sample": { "id": "d77efb5f20cf7a4e", "mode": "clip", "start_beat": 16, "loop": true, "warp": "beats", "fit_beats": 8 } }
```

| Mode | In Live | Fields |
|---|---|---|
| `clip` | audio track; `Track.create_audio_clip` at `start_beat`, copied back to back with `loop`, cut at `length_beats` and at the song's end. No patterns. | `start_beat`, `length_beats`, `loop`, `warp` (`off`, `beats`, `complex`), `fit_beats` (warped: the whole file's length in beats; default the nearest whole bars), `transpose` |
| `one_shot` | MIDI track, Simpler (`replace_sample`) in One-Shot mode, unwarped; pitch 60 as recorded | none; patterns play it |
| `slices` | the same in Slicing mode, slices placed by hand (Manual) at `slices` seconds; pitch 36 the first | `slices` |

A sample's track starts at the level that brings it to -23 LUFS, where the palette's instruments sit, then
`gain_db`. The booth takes samples only in the modes `samples` in `config.toml` lists (`samples = ["clip"]`); with
none, uploads answer `403 samples_off`, check refuses sample parts and the guide doesn't mention them.
`booth sample FILE` keeps a file the way the endpoint does, for a watched `booth run`.

## Tests

```bash
uv run pytest -q -p no:cacheprovider
```

A fake Live runs the LOM code the booth generates against a small model of a song, so the tests need no Live.
