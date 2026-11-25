# Talking to Live through the app

I want one door to Live: `zpkt app`. Everything else is a client of it. The app queues each job, holds one lock, and
writes down who asked. This page is for a program that used to open its own connection: music-bot's booth, zpkt-demo,
a script.

## Step A: the one-line switch

Your code builds a `LiveClient` and runs code strings. Change that one line.

```python
# before
live = LiveClient()
# after
live = LiveClient.via_app("booth")        # or "demo"
```

`via_app(who)` returns a transport with the same `run(code)` and `execute(code)`. Every other call stays. The code
runs in the app's connection, under its lock, as a `live.run` command stamped `booth` (or `demo`, `cli`, `agent`).
Each transport has a group, so what one program does in one run is one group in the app's history.

To switch without touching the code, set `ZPKT_LIVE_VIA=app` and build the client with `LiveClient.default("booth")`.
`ZPKT_LIVE_VIA=direct` (or unset, through `default`) keeps the old direct connection.

For music-bot's booth: where it builds `LiveClient(...)` (it passes `host` and `port` today), use
`LiveClient.via_app("booth")`; `host` and `port` are not needed, the app has them. For zpkt-demo, the same with
`"demo"`. I did not edit those repos.

If the app is down, a call returns an error that starts with "Cannot reach the zpkt app" (`run` raises `LiveError`).
Nothing is sent to Live behind its back.

## Step B: named jobs, no Live code

When a repo only needs a few jobs, it imports `zpkt.app.client` (standard library only) and sends them by name:

```python
from zpkt.app.client import AppClient

app = AppClient("booth")
app.open_set("booth_set")
app.set_tempo(128)
status, reply = app.render_loop("loop.wav", start=0, length=32)
```

| Job | Method | Route (POST under /api/v1) | Does |
|---|---|---|---|
| run | `run(code)` | `/live/run` | a code string, queued, locked, logged |
| read | `submit("live.read", ...)` | `/live/read` | code that only reads (refused if it writes) |
| open set | `open_set(name)` | `/live/open-set` | open a set and wait until Live answers |
| render loop | `render_loop(out, start, length)` | `/live/render-loop` | Live's Export, loop brace or a range |
| set tempo | `set_tempo(bpm)` | `/live/tempo` | `song.tempo` |
| transport | `transport("play"/"stop"/"seek"/"loop")` | `/live/transport` | play, stop, seek, loop |
| state take / put | `state_take()`, `state_put(state)` | `/state/take`, `/state/put` | the mix as data, and back |
| page apply | `page_apply(name, state=, spec=)` | `/page/apply` | a panel's values, next render |
| describe | `describe(keys)` | `/describe` | kind, range and unit of each control |

Every job takes `expect_set` in its args: the set it is for. If Live has another open, the app answers 409 and sends
nothing. A job that changes Live and names no set is held to the set the app last saw open: the desk's set when the
app starts, then the set the app opened (`open_set`), or one a caller named and Live had. `zpkt live open` and
`session.open_set` through `via_app` tell the app too. A read that names no set looks at whatever is open. A reply is `(status, JSON)`. A refusal is a status, never an exception; only an unreachable app raises
`AppDown`. The shapes are in `lib/contracts/app-api.schema.json`.

## Who may ask, and how

- `who` is `cli`, `booth`, `demo` or `agent`. The web page is `you`, and cannot run these jobs.
- An agent may read. For a change it needs `approval` of `option:<id>` (an Option was picked). It cannot send
  `user`; that word is yours.
- The API listens on `127.0.0.1:8984` (`ZPKT_API_PORT`; the client finds it with `ZPKT_APP_URL`). It turns away any
  other Host name.
- Every call but `/health` carries the token in `~/.config/zpkt/app-token` (mode 0600, made when the app starts;
  `ZPKT_CONFIG_DIR` names another folder). The client reads it. It is never logged.

## The `zpkt` command

`zpkt live ...` commands that change Live go through the app. With the app down they stop and say so. `--direct`
talks to Live itself for repair and warns that the change is not recorded. Commands that only look (`ping`,
`check`, `describe`, `selection`, `state take`, `state diff`, `device list`, `page lint`, `panel params`, and
`exec` of code that only reads) may run direct. Names, flags, output and exit codes are the same.

`ZPKT_LIVE_VIA=direct` makes every command direct without the warning: the old way, for a program that has not
moved yet (Zpkt web's `hands panel` calls, until the app runs beside it).
