# zpkt.app

I want one interface for my techno toolkit, and one door to Live. This is the door.

Only `zpkt.app` talks to Live. Everyone else is a client of it: the phone, the desktop, the MiniLab, an agent, the
`zpkt` command, the booth. The app opens the connections once and hands them to `zpkt.live` and `zpkt.audio`, which
are libraries and never open one.

## How it fits

```
adapters        web · API (now) · MiniLab · agents (later)      turn what they hear into Commands
   |
the bus         bus.py       who, the checks, one dispatch table, a log
   |
services        desk.py      state, history, checkpoints, the pager in Live
                monitor.py   Now, Pin, Reference, level match, transport
   |
libraries       zpkt.live    state, describe, monitor_tracks, meter, desk_pager, pages
                zpkt.audio   levels (dB), measure
   ^
connections     connections.py   the one LiveClient and the meter's socket, one lock
```

A call goes down: an adapter makes a `Command(kind, who, args)`, the bus checks it and runs its handler, the handler
asks a service, and the service calls a `zpkt.live` function with the app's connection as an argument. Nothing in
`zpkt.live` or `zpkt.audio` reaches out on its own. `tests/app/test_boundaries.py` proves it from the source.

## The bus

`who` is one of `you`, `minilab`, `agent`, `booth`, `demo`, `cli`, `sys`. The web is always `you`. Each command has an
effect: `read`, `make` (pages, files, versions) or `move` (changes Live). The checks, in order:

- **who** must be one of the seven.
- **The agent rule.** An agent may read, make pages and propose Options. A `move` from an agent needs `approval`:
  `"user"` (you said so) or `"option:<id>"` (an Option was picked). Its changes always have a group, and the first
  change of a group saves a version first, so one undo takes the group back.
- **The wrong-set guard.** A `move` is refused when Live has another set open than the one the page is for. Nothing is
  sent. A set Live does not name (unsaved) passes. The answer is kept for five seconds.
- **The lock.** Live takes one job at a time. A command that cannot get it in five seconds answers 503 and says Live
  is busy. It is never dropped silently.

Every applied move is a history entry with its `who` (and its group) and, once it settles, one `Change` per control
in the set's change stream (`zpkt.live.changes`, `GET /api/changes?since=N&who=agent`).

## What it serves

`zpkt app` (or `uv run python contrib/mixdesk/server.py`, which starts the same thing) listens on 8985 as the mix desk
always did, with the pager's datagrams on 8986 and the meter on 8987.

- `/` is the old desk page, unchanged. All its routes, event shapes and ports are as they were.
- `/app/` is the new shell: the Hear bar (bar, spectrum from the meter, "N changed", what you hear, Play, Now / Pin /
  Ref, undo, redo, history) and the Desk. It reads the same state through `/events?app=1`.
- `POST /api/command` takes any command: `{"kind": "mix.set", "args": {"norms": [["Kick bus/volume", 0.4]]}}`.
  `GET /api/commands` lists them. The old `POST /api/...` paths are these commands under their old names.

## The API and its clients

`zpkt app` also starts the API adapter on 127.0.0.1:8984 (`ZPKT_API_PORT`). It is how the `zpkt` command, the booth and
the demo reach Live (docs/app-clients.md). Every call is a Command stamped `cli`, `booth`, `demo` or `agent`, and needs
the token in `~/.config/zpkt/app-token` (mode 0600, made at start). The jobs are in `jobs.py`; the client in
`client.py` (standard library only, no Live code); the transport that lets a `LiveClient` caller switch in one line in
`zpkt.live.app_transport`. The web page is `you` and cannot run them. The shapes are `lib/contracts/app-api.schema.json`.

## Options and the one render queue

An Option is a set of Versions of the mix, made to be heard side by side. I look at them in the Options sheet of
`/app/` (the Options tab): a grid of Versions with their loudness and their gap to the base. Tapping one puts its
numbers and spectrum on the Hear bar. "Make it Now" puts a Version's values on the mix as one move, which one undo
takes back.

- `options.make` asks for one: `{"title": "Kick up", "versions": [{"label": "+3 dB", "writes": [["Kick bus/volume",
  0.8]]}], "range": {"start_beat": 64, "length_beats": 32}}`. The first Version is the mix as it stands (the base).
- `renders.py` is the worker. For each Version it writes the values, has Live export through `zpkt.live.export` with
  the app's connection, puts the values back (whatever happens), and hands the WAV to `zpkt.audio.measure`. Progress
  streams as `{"t": "option"}` messages ("rendering 2 of 3"). Live is held for one Version at a time.
- The queue is `renderqueue.py` (it came from `contrib/arranger/`, whose `renderqueue` is now an alias for it). Jobs
  are files under `<data>/options/jobs`, in the shape of `lib/contracts/option.schema.json`.
- Mix 2, the spectral fixes, the kick options and `hands panel grid` still render in their own tools, into their own
  folders. The app reads those and lists them as Options. It changes none of them, so the old pages work as before.
- `options.list`, `options.get`, `options.show` (reads) and `options.pick` (a move) are commands on the bus. An agent
  may make an Option. It needs your word or an Option pick to make a Version Now.

## Files that stay where they were

The desk's own files stay in `contrib/mixdesk/`: `desk.json`, `sources.json`, `pager.py` (it runs inside Live) and
the old page. `ZPKT_MIXDESK_DIR` names another folder. The old module names there (`history`, `protocol`, `deskstate`,
`surfaces`, `server`) are aliases for the modules here, so old imports and tests keep working.

## How to add an adapter

1. Add a module to `zpkt/app/adapters/`, say `midi.py`.
2. In it, write a class with `name`, `start()` and `stop()`. Its constructor takes an `AppContext` (the bus, the desk
   and the settings).
3. End the module with `ADAPTER = AdapterSpec("midi", MidiAdapter)`.
4. Turn what it hears into `Command(kind, "minilab", args)` and call `context.bus.submit(...)`. That is all it may do
   to Live: an adapter imports nothing from `zpkt.live` (a test checks it).
5. Start it with `zpkt app --adapters web,midi`.

`adapters.discover()` finds every module that defines `ADAPTER`, so the core is not edited.

## How to test it

`uv run pytest tests/app`. The tests use `FakeLive` (handed straight to the connections, no port), a fake meter socket
and free ports. They never touch the running desk, a MiniLab or the real Live. `make check` runs all of it.
