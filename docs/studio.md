# studio: the voice production app

A chat with Claude Code that works by voice. You talk on your phone, Claude works on the Mac (Live, zpkt), and the
answer comes back as speech and as music in the same chat. The plan is in `docs/plan-2026-10.md` (Phase 2).

It runs on the Mac inside `harness serve` and is reached over the tailnet only, behind the harness password, at `/`
(which opens `/studio/`). The /skrng pages stay at `/skrng/`.

## A turn

The mic and the speaker take turns: they are never on together, so a car's Bluetooth stays in its media profile.

1. **You talk.** The phone streams the mic to the Mac. Captions follow you live (folded by default). You end the turn
   by saying **"tomato"**. Pauses don't end it, so you can think mid-sentence. You can also tap to end the turn, or type.
2. **Claude works.** The transcript goes to one long-lived Claude Code session (cwd: zpkt). While it works, a small
   Haiku model narrates what it is doing in a few words, and screenshots of its actions arrive at the level you chose.
3. **Claude answers.** Its words are spoken (Kokoro, on the Mac, streamed as it is generated). Music it renders arrives
   as its own bubble. With autoplay on (the default) both play in order.
4. **Your turn again.** When the phone has finished playing, the mic opens.

"Play again" and "loop that three times" replay the last music at once, without waiting for Claude: a small command
parser catches them and calls the same `play_music(loops=N)` tool Claude has. Claude is told about it on its next turn.

## Processes

```
phone (Safari/Chrome)  ──https, tailnet──▶  tailscale serve  ──▶  harness serve (127.0.0.1:8787, aiohttp)
                                                                   ├─ /studio/      the app: page, WebSocket, history, media
                                                                   ├─ Claude Code session (Agent SDK) + studio tools (MCP)
                                                                   ├─ Haiku narrator (Agent SDK)
                                                                   ├─ screenshots (capture, saliency, WebP pairs)
                                                                   └─ voice worker (child process, lib/voice)
                                                                        Kokoro TTS, VAD + STT, stop word
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
  conversation.py  the turn loop: phases, who has the turn, what plays next
  agent.py         the Claude Code session: streaming text, tool activity, interrupt, resume
  tools.py         the tools Claude gets from the app (present_music, play_music, stop_audio, screenshot)
  intents.py       spoken commands handled without Claude (play again, loop N times, stop)
  speech.py        the voice worker's client, and the speaker: text to segments to streamed audio to a replay file
  narrator.py      Haiku narration: rate-limited, stale lines dropped
  screens.py       screenshot pairs at the chosen level
  timing.py        per-turn timing marks (V1 measurement)
  static/          the page: plain ES modules, no build step
lib/voice/src/voice/
  protocol.py      the frame codec, shared with the harness (no heavy imports)
  worker.py        `voice serve`: reads requests on stdin, writes replies on stdout
  tts.py           Kokoro: text normalisation, segmenting, streaming synthesis
  stt.py           VAD + speech-to-text + the stop word, one turn at a time
```

## The chat

Every chat item is a **message** with a kind. Messages are stored in SQLite (`~/_agent_scratch/studio/`, outside the
repo) and served in pages. Media (speech replays, music, screenshots) is content-addressed and served immutable.

| kind | what | data |
|---|---|---|
| `user` | what you said (or typed) | `text`, `source` (voice/typed), `audio` (your recording), `duration`, `intent` |
| `agent` | what Claude said, or a narration | `text`, `role` (reply/narration), `audio` (replay), `duration`, `streaming` |
| `music` | a render to listen to | `title`, `audio` (FLAC), `duration`, `ab` (bar length, bars, first side, labels), `plays`, `note` |
| `shots` | a screenshot pair | `level`, `caption`, `full`, `zoom`, `rect`, `screen` |
| `activity` | a tool call | `tool`, `title`, `detail`, `status` (running/ok/error), `ms` |
| `notice` | the app itself speaking up | `level` (info/warn/error), `text` |

Wire form: `{"seq": 41, "kind": "agent", "created": 1760000000.1, "turn": "t…", "rev": 2, "data": {…}}`. `seq` is the
message's id and its order; `rev` grows on each update (a reply's text and audio arrive after the bubble does).
A media reference is `{"url": "/studio/media/<sha256>.<ext>", "type": "<mime>", "bytes": n}`; screenshot refs add
`w` and `h`.

Captions of speech (yours and Claude's) are in the message text; the page folds them by default.

The page keeps at most a window of messages in the DOM and in memory (a cap of about 60). Older ones are dropped as
new ones arrive; a **Load earlier** button (with a spinner) fetches the previous page from the server. Decoded audio
is kept in a small LRU.

## Screenshots

Levels: **none**, **major** (default), **minor**, **firehose**. Each shot is a pair: the full screen and a zoom into
what changed (the difference from the previous capture, else a hint, else the front window), WebP, sized to keep text
legible. What counts as what:

- major: the end of a turn in which the screen changed, an explicit `screenshot` call by Claude, and steps a script
  reports as major;
- minor: every tool call (before/after difference), and steps scripts report as minor;
- firehose: a capture every second or so while a tool runs (only when something changed), and every reported step.

Nothing is captured below the highest level any connected page asked for. Scripts report steps by posting to a
loopback-only endpoint whose URL and token are in their environment (`STUDIO_STEP_URL`, `STUDIO_STEP_TOKEN`).

## WebSocket protocol (`/studio/ws`)

Text frames are JSON objects with a `type`. Binary frames start with one byte naming the channel:
`0x01` mic audio (phone → Mac: signed 16-bit little-endian PCM, 16 kHz mono), `0x02` speech audio (Mac → phone: then
a 4-byte big-endian stream id, then signed 16-bit little-endian PCM at the stream's rate).

Phone → Mac:

| type | fields | meaning |
|---|---|---|
| `hello` | `client`, `prefs`, `ua` | first message; `prefs` = `{autoplay, shots, handsfree}` |
| `prefs` | `prefs` | preferences changed |
| `start` | | this phone takes the mic and speaker; hands-free on |
| `pause` | | hands-free off: the mic stays closed until `start` |
| `mic` | `state` (open/closed), `turn`, `open_ms` | the mic opened (and how long that took) or closed |
| `say` | `text` | a typed turn |
| `end_turn` | | end my turn now (same as saying the stop word) |
| `interrupt` | | stop Claude and everything playing; my turn |
| `playback` | `state` (busy/idle), `done` | the phone started playing, or has played everything; `done` counts the items it has finished or dropped |
| `mark` | `turn`, `name`, `ms` | a timing mark measured on the phone |
| `ping` | `t` | keepalive |

Mac → phone:

| type | fields | meaning |
|---|---|---|
| `welcome` | `conversation`, `phase`, `turn`, `label`, `owner`, `speech_ready`, `page` (`items`, `has_more`), `version` | after `hello` |
| `phase` | `phase` (idle/listening/working/responding), `turn`, `label` | whose turn it is, and what Claude is doing |
| `listen` | `turn` | open the mic now (sent to the phone that owns it) |
| `unlisten` | `turn` | close the mic now |
| `caption` | `turn`, `text` | the live transcript of the turn so far |
| `upsert` | `message` | a message is new or changed |
| `speech` | `stream`, `seq`, `rate`, `state` (begin/end) | a speech stream starts or ends; its audio comes in `0x02` frames |
| `play` | `seq`, `loops` | play a music message, after anything already queued |
| `stop_audio` | | stop and clear everything playing (and restart the `done` count) |
| `reset` | `conversation` | a new conversation started: clear the chat |
| `notice` | `level`, `text` | a passing notice |
| `pong` | `t` | |

**Counting items.** An item is one `speech` stream (begin to end) or one `play` command. The phone counts every
item it finishes or drops (stopped, interrupted, replaced by a tap) and reports the count in `playback`; the count
restarts when the phone sends `start` and when it receives `stop_audio`. The Mac opens the mic only when the count
has caught up with what it sent, so a lost message can't open the mic over the music. Speech streams are sent only
to a phone with autoplay on; `play` commands are explicit requests and play either way.

HTTP (all behind the password): `GET /studio/api/messages?before=<seq>&limit=<n>` →
`{"items": [...oldest first...], "has_more": bool}`; `GET /studio/api/timings?turns=<n>`;
`POST /studio/api/conversation` starts a new conversation; `GET /studio/media/<name>`.

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
Tests: `uv run --project lib/harness pytest` and `uv run --project lib/voice pytest`.
