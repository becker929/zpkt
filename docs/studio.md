# studio: the voice production app

A chat with Claude Code that works by voice. You talk on your phone, Claude works on the Mac (Live, zpkt), and the
answer comes back as speech and as music in the same chat. The plan is in `docs/plan-2026-10.md` (Phase 2).

It runs on the Mac inside `harness serve` and is reached over the tailnet only, behind the harness password, at `/`
(which opens `/studio/`). The /skrng pages stay at `/skrng/`.

## A turn

The mic and the speaker take turns: they are never on together, so a car's Bluetooth stays in its media profile.
Between turns the phone keeps its mic stream with the tracks disabled (menu: Keep the mic ready, on by default),
so a browser that asks for the mic on every getUserMedia (Chrome on iOS) asks once. With it off, closing stops the
tracks, which is the surest way back to Bluetooth's media profile.
The page records from the phone's own mic when it has one (menu: Studio mic, on), so a car's or headset's
Bluetooth only ever plays and need not switch to its call profile; the first request can't name a device (names
come with permission), so the phone's mic is used from the next open on.

1. **You talk.** The phone streams the mic to the Mac. Captions follow you live (folded by default). You end the turn
   by saying **"tomato"**. Pauses don't end it, so you can think mid-sentence. You can also tap to end the turn, or type.
2. **Claude works.** The transcript goes to one long-lived Claude Code session (cwd: zpkt). While it works, a small
   Haiku model narrates what it is doing in a few words, and screenshots of its actions arrive at the level you chose.
   Its thinking, tool calls and screenshots fold into one trace bubble in the chat (never spoken).
3. **Claude answers.** Its words are spoken (Kokoro, on the Mac, streamed as it is generated). Music it renders arrives
   as its own bubble at once, but plays only after Claude's turn is over, after everything it said: for each render,
   in order, the app says its title, then its note, then "Three, two, one.", and the music starts as the count-in
   ends. With autoplay on (the default) all of it plays in order; with it off, nothing is spoken or played by itself.
4. **Your turn again.** When the phone has finished playing, the mic opens.

Music never starts unannounced, and words about it never come after it: on the phone, in a car, there is nothing to
look at. So the order is Claude's words, then the intro, then the music. The intro is the app's, not Claude's: the
render's `title` and its `note` (one or two sentences, what it is and what to listen for), which Claude writes for
`present_music` knowing they are spoken just before the music, so its reply needs only a few words about it. Once
Claude has put music in the turn, the narrator says nothing more (a line being written is dropped, and so are lines
waiting to be spoken): the intro says what the music is. A narration already playing ends first; the phone plays
everything in order, so nothing is ever heard over anything else. Interrupting drops the music still waiting.

"Play again" and "loop that three times" replay the last music at once, without waiting for Claude: a small command
parser catches them and calls the same `play_music(loops=N)` tool Claude has. Their intro is short ("Again: Kick
drive. Three, two, one."), said once however many loops. Claude is told about it on its next turn. When Claude itself
calls `play_music`, the replay waits for the end of its turn like a render. Music presented while no turn of Claude's
is running gets its full intro and plays at once. With autoplay off a replay plays without an intro, and a tap on a
bubble always plays it at once, with no intro.

## Processes

```
phone (Safari/Chrome)  ──https, tailnet──▶  tailscale serve  ──▶  harness serve (127.0.0.1:8787, aiohttp)
                                                                   ├─ /studio/      the app: page, WebSocket, history, media
                                                                   ├─ Claude Code session (Agent SDK) + studio tools (MCP)
                                                                   ├─ Haiku narrator (Agent SDK)
                                                                   ├─ screenshots (capture, saliency, WebP pairs)
                                                                   └─ voice worker (child process, lib/voice)
                                                                        Kokoro TTS, Silero VAD + Parakeet STT, stop word
```

The speech models run in their own process (`lib/voice`, `voice serve`) so their native runtimes never block the web
server's event loop, a crash in them is a restart rather than an outage, and their heavy dependencies stay out of the
harness. The harness starts the worker and talks to it over its stdin and stdout (frames, below).

## Code

```
lib/harness/src/harness/studio/
  model.py         messages, their kinds, phases, preferences, screenshot levels
  store.py         SQLite message store (paging), content-addressed media, turn timings
  hub.py           connected phones: one writer task each, fan-out, the one that owns mic and speaker
  protocol.py      the WebSocket's JSON messages and binary frames
  routes.py        routes: page, static files, history, media, WebSocket
  assets.py        the page's files: versioned URLs cached for good, gzipped once, modulepreloads, first page
  conversation.py  the turn loop: phases, who has the turn, what plays next (music after Claude's words, each with
                   its intro); a turn that fails hands the mic back
  turn.py          one Claude turn's events as chat messages: replies (spoken), thinking, tool calls
  playback.py      what the owner's phone has still to play, counted back, before the mic opens
  agent.py         the Claude Code session: streaming text and thinking, tool activity, interrupt, resume
  tools.py         the tools Claude gets from the app (present_music, play_music, stop_audio, screenshot); their
                   descriptions tell Claude when the music plays, and that present_music's `note` is spoken in its intro
  intents.py       spoken commands handled without Claude (play again, loop N times, stop)
  speech.py        the voice worker's client, and the speaker: text to segments to streamed audio to a replay file
  narrator.py      Haiku narration: rate-limited, stale lines dropped, quiet once music waits for the turn's end
  screens.py       screenshot pairs at the chosen level: when to capture, and the chat messages
  shots.py         saliency (what changed), the 4:3 zoom, WebP presets per level
  grab.py          the capture: screengrab.swift (ScreenCaptureKit), built on first use; screencapture fallback
  guard.py         the hard rules on the session's shell commands
  activity.py      tool calls in a few words
  timing.py        per-turn timing marks (V1 measurement)
  migrate.py       repairs to stored data: old FLAC music to MP3 (`harness studio-music-mp3`)
  static/          the page: plain ES modules, no build step
lib/voice/src/voice/
  protocol.py      the frame codec, shared with the harness (no heavy imports)
  worker.py        `voice serve`: reads requests on stdin, writes replies on stdout
  tts.py           Kokoro: sentences, streaming synthesis; the build to use (VOICE_TTS_MODEL), and the ONNX one
  fluid.py         Kokoro on FluidAudio (Neural Engine): builds the Swift helper (swift/) on first use, talks to it
  stt.py           Silero VAD + Parakeet (MLX) + the stop word, one turn at a time (docs/voice-benchmark.md)
  fake.py          stand-in engines for tests and page work (--tts fake --stt fake)
```

## The chat

Every chat item is a **message** with a kind. Messages are stored in SQLite (`~/_agent_scratch/studio/`, outside the
repo) and served in pages. Media (speech replays, music, screenshots) is content-addressed and served immutable.

| kind | what | data |
|---|---|---|
| `user` | what you said (or typed) | `text`, `source` (voice/typed), `audio` (your recording), `duration`, `intent` |
| `agent` | what Claude said, or a narration | `text`, `role` (reply/narration/note), `audio` (replay), `duration`, `streaming` |
| `thinking` | Claude's thinking, summarized; never spoken | `text` (grows while `streaming`), `streaming` |
| `music` | a render to listen to | `title`, `audio` (gapless V0 MP3: iPhone Safari can't decode FLAC), `duration`, `ab` (bar length, bars, first side, labels), `options` (N renders end to end, below), `plays`, `note` |
| `shots` | a screenshot pair | `level`, `caption`, `full`, `zoom`, `rect`, `screen` |
| `activity` | a tool call | `tool`, `title`, `detail`, `status` (running/ok/error), `ms` |
| `notice` | the app itself speaking up | `level` (info/warn/error), `text` |

Wire form: `{"seq": 41, "kind": "agent", "created": 1760000000.1, "turn": "t…", "rev": 2, "data": {…}}`. `seq` is the
message's id and its order; `rev` grows on each update (a reply's text and audio arrive after the bubble does).
A media reference is `{"url": "/studio/media/<sha256>.<ext>", "type": "<mime>", "bytes": n}`; screenshot refs add
`w` and `h`.

Captions of speech (yours and Claude's) are in the message text; the page folds them by default.

**Thinking.** The session runs with adaptive thinking and `display: summarized` (`Studio._options`): for current
models Claude Code otherwise sends thinking blocks with no text, only a signature. The summary streams as
`thinking_delta` events; the reader turns each block into a `thinking` message that grows like a reply. It is not
spoken and not narrated.

**The trace.** Consecutive `thinking`, `activity` and `shots` messages render as one trace bubble; any other kind
(`user`, `agent` including narrations, `music`, `notice`) ends the run, and the next one starts a new trace. Folded
(the default) it is one line: the step running now or the last one (a thought by its heading or first sentence), the
latest zoom as a thumbnail, how many steps and shots, and a spinner while anything runs (a cross if a step failed).
Unfolded: the items in order, thinking as dimmed text, tool calls as rows that open to their command and output,
screenshot pairs that open the lightbox. Shots above the page's level are hidden and not counted. The fold is
remembered by the items' seqs, so a trace that is dropped and paged back in, or split and joined again, comes back
as the reader left it.

The page keeps at most a window of messages in the DOM and in memory (a cap of about 60). Older ones are dropped as
new ones arrive; a **Load earlier** button (with a spinner) fetches the previous page from the server. A trace cut by
a page boundary grows at its front when the older page arrives. The view keeps the reader's place itself: the first
message in view stays put; inside an unfolded trace that is the item being read, and a folded trace counts as one
block. Decoded audio is kept in a small LRU.

## Making music: plans, the render cache, A/B every bar

The voice loop changes the music by **plans**. A plan is a small JSON document that says which knobs of a base set
take which values, for one section:

```json
{"kit": "c8x4", "knobs": {"rumble|plugin:Decapitator|Drive": 0.5, "chord|Eq8:0|Bands.1/ParameterA/Gain": 6.0},
 "label": "kick drive 50%"}
```

- **kit**: a probe kit (`hands/scripts/probe_pack/probe_kit.py`): a copy of the set trimmed to a lead-in plus one
  section repeated P times. Kits are built once, in the GUI, and reused. A kit is the plan's base; its version is
  the hash of its XML.
- **knobs**: ids `<track>|<device>|<parameter>` (`hands/src/hands/plans/model.py`): device `Mixer`,
  `plugin:<name>` or `<DeviceTag>:<index>`; values in the set's own units, ranges read from the set. Knobs a plan
  leaves out keep the kit's value.

**Rendering packs plans.** Plans on the same kit are written into one copy of the kit, one pattern each, and
rendered with one load and one export (probe_kit): about 7 s to load and 13 s plus a tenth of the audio's
length to export. Four plans cost barely more than two, so every render is a **write-ahead**: with the A/B it renders
the likely next asks too ("more": B pushed as far again; "the other end": A pushed the other way). When Anthony says
"more", that A/B is already rendered and plays within a second.

**The cache** keeps every render by its key: the kit's version plus the canonical plan (knobs sorted, values
rounded, knobs at the kit's value dropped). A plan already rendered plays at once. **Nearest neighbour**: knob values are scaled to their ranges, so
distances compare across knobs; a cached plan within a small distance is offered while the exact one renders.

**A/B every bar.** Two renders of the same section become one file: each is set to the same loudness (BS.1770
integrated, -14 LUFS), the first bar (the previous pattern's tail) is dropped, and bars alternate A, B, A, B with 10 ms crossfades.
The file goes to the chat with `present_music` and its `ab` metadata (bar length, bars, which side starts, labels),
and the page lights A or B in time. Its `note` says which side is which and what to listen for: it is spoken
right before the A/B plays.

**Options, switched on the phone.** An A/B compares two renders; options put N of them in one file
(`hands/src/hands/plans/options.py`): one knob at N values (`hands plan slider`), N steps from one plan to another
(`hands plan line`), or any plans (`hands plan options`). They bake through the cache like any plans, P to a Live
pass. Each option is cut to `bars` bars after its pattern's first bar, made to loop (its first 10 ms crossfade from
what follows its last bar), and measured: `match_db` brings each to -14 LUFS, less one shared offset so no peak
passes -1 dBFS. The file stays under 135 s, because the phone keeps it decoded.

`present_music` takes the printed `options` (layout `slider` or `buttons`, name, bar length, bars, which option
sounds like the set now, each option's label and `match_db`), checks it against the file's length, and the
music message keeps it. The page fetches the file as soon as the card is in the chat, before any tap, and decodes
it as soon as there is an audio context. From then on nothing goes to the Mac until a choice is made:

- the Mac's `play` (autoplay, after the card's intro) **sweeps**: option k sounds during bar k, one bar of each, in
  order;
- a tap on the card, or on the slider, **holds** an option: it loops its bars until stopped (at most ten minutes);
- moving the slider or tapping a button switches 15 ms later, at the same place in the bar: every option is read at
  `(t - t0) mod its length`, so the beat goes on. The switch is a 12 ms crossfade, and touching a sweep turns it into
  a hold;
- **Match loudness** ramps each option to its `match_db`;
- a held option gives way to anything the Mac sends (speech, music) at the next bar line;
- **Keep** and **Finer here** stop the sound and send Anthony's next turn as text ("Keep rumble Drive at 62%: option
  6 of 9 on card 41."), which Claude maps back to the option's plan (skill options-slider).

On a touch screen the slider picks on a tap, or once a touch moves sideways, so a thumb scrolling the chat past the
card does not start it. The page side is `static/js/options.js` (the arithmetic), `options-clip.js` (the
player: a looping source per sounding option, a fade, and a match gain per option) and the card in `bubbles.js`.

These are skills in `.claude/skills/` (render-plan, ab-1bar, plan-cache, options-slider) over one CLI, `hands plan` (the package
`hands/src/hands/plans/`, extra `plans`), so Claude uses them like any other script and they keep growing:

```bash
cd hands && uv run --extra plans hands plan ab A.json B.json     # -> {path, title, ab, ahead: [more, other end]}
```

The cache is `~/_agent_scratch/plans/` (`HANDS_PLANS`). Renders go through probe_kit's guards (no dialog, one of our
sets in front, Live answering) and stop rather than guess.

## Screenshots

Levels: **none**, **major** (default), **minor**, **firehose**. Each shot is a pair: the full screen and a zoom into
what changed, WebP. What counts as what:

- major: the end of a turn in which the screen changed, an explicit `screenshot` call by Claude, and steps a script
  reports as major;
- minor: every tool call (the zoom shows what it changed), and steps scripts report as minor;
- firehose: a look every second while a tool runs (posted only when something changed), and every reported step.

Nothing is captured below the highest level any connected page asked for. Scripts report steps by posting to a
loopback-only endpoint whose URL and token are in their environment (`STUDIO_STEP_URL`, `STUDIO_STEP_TOKEN`).

**Never in Claude's way.** The hook before a tool captures nothing, and the hook after it queues the tool's shot and
returns at once. Captures are taken one at a time, each compared with the one before it: the previous step's, or the
turn's first, which is taken in the background as the turn starts (the turn's end is compared with it too). Those
are the only frames kept.

**Capture.** A small ScreenCaptureKit helper (`studio/screengrab.swift`) stays running; a capture costs ~40 ms. At
firehose level it holds a stream open while a tool runs (2 fps, opened at the first look, so quick tools never open
it): a look reads the latest frame in a few ms, and a still screen gives the same frame again, so there is nothing to
compare. The harness compiles the helper on first use (a few seconds) into the data directory, as
`bin/screengrab-<hash of its source>`, so no binary is committed. Without `swiftc`, or when the helper keeps failing,
`screencapture` takes over (~130 ms, converted from the display's colour profile to sRGB).

Screen Recording belongs to the process that started the harness: run it in tmux, which holds the permission.
Without it a capture shows only the wallpaper, so screenshots turn off instead, and the chat says why, once.

**The zoom** goes where the screen changed. Changed pixels are counted in 8 px cells and nearby cells are grouped;
the group a zoom can show most of wins, weighted by how much of the zoom it fills, so a dialog beats a sprawling
re-layout, and a caret, a meter or the playhead counts for little. The menu bar (its clock) is ignored. Near a hint
(where Claude acted) a change counts four times as much, and far from it only a big one wins. While a tool is
watched, what keeps changing on its own (video, meters, the playhead) is learnt and ignored. With no change: the
hint, then the front window (a modal alert counts), then the centre. The zoom is 4:3, from 480x360 to 960x720.

**Sizes.** major and minor: the full screen at native 1080p, q75 (73-111 KB), and the zoom at native pixels, q90
(9-46 KB). Over budget (120 KB, 60 KB) the quality steps down to q50, then the full screen shrinks; the zoom is never
resized. firehose: the full screen at 720p, q70 (~52 KB), and the zoom at q85. `rect` is the zoom in screen pixels
and `screen` the capture's size: the page outlines the zoom on the full image, scaled by `full.w / screen[0]`.

## WebSocket protocol (`/studio/ws`)

Text frames are JSON objects with a `type`. Binary frames start with one byte naming the channel:
`0x01` mic audio (phone → Mac: signed 16-bit little-endian PCM, 16 kHz mono), `0x02` speech audio (Mac → phone: then
a 4-byte big-endian stream id, then signed 16-bit little-endian PCM at the stream's rate). Speech goes out in 0.1 s
frames, so the phone starts on the first one instead of waiting for a whole sentence (Kokoro makes one at a time,
~150 KB: most of a second on a slow link). The page plays each frame with one sample of its neighbours on either side
(`speech-stream.js`): the browser resamples every buffer on its own, and a buffer without them clicks at its edges.

Phone → Mac:

| type | fields | meaning |
|---|---|---|
| `hello` | `client`, `prefs`, `ua` | first message; `prefs` = `{autoplay, shots, handsfree}` |
| `prefs` | `prefs` | preferences changed |
| `start` | | this phone takes the mic and speaker; hands-free on |
| `pause` | | hands-free off: the mic stays closed until `start` |
| `mic` | `state` (open/closed), `turn`, `open_ms` | the mic opened (and how long that took) or closed |
| `say` | `text` | a typed turn; the page that sends it takes the speaker (unless another one has it mid-turn) |
| `end_turn` | | end my turn now (same as saying the stop word) |
| `interrupt` | | stop Claude and everything playing; my turn |
| `playback` | `state` (busy/idle), `done` | the phone started playing, or has played everything; `done` counts the items it has finished or dropped |
| `mark` | `turn`, `name`, `ms` | a timing mark measured on the phone |
| `log` | `text` | something went wrong on the page (audio that didn't play); goes to the harness log |
| `ping` | `t` | keepalive |

Mac → phone:

| type | fields | meaning |
|---|---|---|
| `welcome` | `conversation`, `phase`, `turn`, `label`, `owner`, `speech_ready`, `page` (`items`, `has_more`), `version` | after `hello` |
| `phase` | `phase` (idle/listening/working/responding), `turn`, `label` | whose turn it is, and what Claude is doing |
| `listen` | `turn` | open the mic now (sent to the phone that owns it) |
| `unlisten` | `turn` | close the mic now |
| `owner` | `owner` | this page has just gained (`true`) or lost (`false`) the mic and the speaker |
| `caption` | `turn`, `text` | the live transcript of the turn so far |
| `upsert` | `message` | a message is new or changed |
| `speech` | `stream`, `seq`, `rate`, `state` (begin/end) | a speech stream starts or ends; its audio comes in `0x02` frames. `seq` is the bubble it speaks for: a reply, a narration, or a music bubble (its intro: the card lights while it is said) |
| `play` | `seq`, `loops` | play a music message, after anything already queued; with autoplay on it comes the moment its intro's stream ends |
| `stop_audio` | | stop and clear everything playing (and restart the `done` count) |
| `reset` | `conversation` | a new conversation started: clear the chat |
| `notice` | `level`, `text` | a passing notice |
| `pong` | `t` | |

**Counting items.** An item is one `speech` stream (begin to end) or one `play` command. The phone counts every
item it finishes or drops (stopped, interrupted, replaced by a tap) and reports the count in `playback`; the count
restarts when the phone sends `start` and when it receives `stop_audio`. The Mac opens the mic only when the count
has caught up with what it sent, so a lost message can't open the mic over the music. A render's intro is a speech
stream like any other, counted the same way. Speech streams are sent only to a phone with autoplay on; `play`
commands are explicit requests and play either way.

HTTP (all behind the password): `GET /studio/api/messages?before=<seq>&limit=<n>` →
`{"items": [...oldest first...], "has_more": bool}`; `GET /studio/api/timings?turns=<n>`;
`POST /studio/api/conversation` starts a new conversation; `GET /studio/media/<name>`.

Loading over a slow link (`assets.py`). `GET /studio/` is never cached and carries the newest page of history
(`<script id="boot">`), which the page shows before its socket is up. It links the scripts and styles as
`/studio/static/<version>/...`, where the version hashes every file in `static/`: those URLs are cached for good
(`immutable`) and gzipped, and a deploy changes the version, so the next load fetches the new files; the welcome's
`version` includes it too, so a page left open is offered a reload. Every module is listed as a `modulepreload`, so
they are fetched in one round trip rather than one per level of imports. The history and timings API answer gzipped.
Measured through a link like a car's (150 ms round trip, 2 Mbit/s down) with a 40-message chat: the chat showed
2.3 s after a first load and 1.5 s after a later one, and now 1.35 s and 0.23 s; a later load is one request
instead of 27 revalidations. Claude's first words reached the speaker 1.1 s after it wrote them, now 0.6 s.

## Voice worker frames (stdin/stdout)

A frame is a 4-byte big-endian header length, a JSON header, a 4-byte big-endian payload length, and the payload
(empty for most). Requests carry an `id`; replies echo it.

| request | replies |
|---|---|
| `{"op": "tts", "id", "text", "voice", "speed"}` | `tts.chunk` (`rate`, `index`) + PCM payload, …, then `tts.end` (`ms`, `error`?) |
| `{"op": "tts.cancel", "id"}` | `tts.end` with `cancelled` |
| `{"op": "stt.begin", "id", "rate", "stop_word"}` | `stt.partial` (`text`) as you talk |
| `{"op": "stt.audio", "id"}` + PCM payload | `stt.final` (`text`, `stop_word`, `audio_s`, `ms`) once the stop word is heard |
| `{"op": "stt.end", "id"}` | `stt.final` now, stop word or not |
| `{"op": "ping"}` | `pong` with the engines' names and load times |

## Security

- Tailnet only (`tailscale serve`, no funnel), then the harness password (scrypt hash, per-browser session cookie).
  The WebSocket is authenticated by the same cookie.
- The step endpoint for scripts listens on loopback only, on its own port that `tailscale serve` does not forward,
  and needs a token made fresh at every start and given only to Claude's environment.
- The Claude session has the same tools as a harness job (Bash, edits and so on) plus the studio tools. It is the
  owner's own session; the same rules apply as at the desk.

## Running

`harness serve` starts everything. Data lives in `~/_agent_scratch/studio/` (override with `HARNESS_STUDIO`).
Tests: `uv run --project lib/harness --extra dev pytest` and `uv run --project lib/voice --extra dev pytest`
(`VOICE_ENGINES=1` and `--extra engines` add the real models). The speech models are fetched on first use: Kokoro
and Silero into `~/.cache/zpkt-voice` (`VOICE_MODELS`; FluidAudio's helper is built there too, about a minute and a
half the first time), Parakeet into the Hugging Face cache. Turn timings:
`harness timings` (docs/voice-benchmark.md).

Music stored before it was MP3 is FLAC, which iPhone Safari cannot play: `harness studio-music-mp3 --dry-run` lists
it, and without `--dry-run` each such bubble gets an MP3 (the FLAC file is kept, and the message keeps its
reference as `original`). Running it again changes nothing; it is safe while the server runs.

The whole stack, end to end (page in Chromium, real server, Kokoro and Parakeet, `hands plan ab` with stand-in
renders): `STUDIO_STACK=1 uv run --project lib/harness --extra dev pytest lib/harness/tests/ui/test_stack.py`; add
`STUDIO_CLAUDE=1` for one typed turn with the real Claude session.
