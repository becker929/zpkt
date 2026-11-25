# zpkt.app

I want one interface for my techno toolkit, and one door to Live. This is the door.

Only `zpkt.app` talks to Live. Everyone else is a client of it: the phone, the desktop, the MiniLab, an agent, the
`zpkt` command, the booth. The app opens the connections once and hands them to `zpkt.live` and `zpkt.audio`, which
are libraries and never open one.

## How it fits

```
adapters        web (now) · MiniLab · API · agents (later)      turn what they hear into Commands
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

## The Song

The arranger is mounted at `/app/song`. Its server stays as it is, on :8975, and the Song serves the same pages and
routes from the same code (`contrib/arranger/server.py`'s route table), so nothing the arranger did changes.

- `/app/song/` is the arranger page; `/app/song/mix/`, `/transitions/`, `/mix2/`, `/spectral/` and `/kick/` are the
  others. Their absolute links gain the prefix on the way out; the files are not edited.
- In the `/app/` shell the Song tab shows the arrangement as lanes of bars. Mix 1 and transitions open as sheets, still
  labelled sketches: they play rendered loops in the browser, within the two named exceptions of
  `contrib/docs/sound.md`. Closing the sheet takes the page, and its sound, away.
- The arrangement file keeps its form. A save from the arranger page keeps every key it does not own, byte for byte
  (`tests/app/test_song.py` checks it, and checks every route against the old server).
- Song is the Structure, Recipe is the Structure and the Sound (`contrib/arranger/arrangement.py`'s types). Commands:
  `song.list`, `song.show` (the Song), `song.recipe` (both halves), the writes `song.save`, `song.keep`,
  `song.delete`, `song.transitions`, `song.queue` (the arranger's routes as commands, so a save is stamped who), and
  `song.build`.
- `song.build` makes the mix set in Live from the recipe (`zpkt.live.recipe_build`, which `mixset.py build` also
  calls), with the app's connection. It is a move for the mix set, not the page's set: the bus checks Live has the mix
  set open, and the build itself refuses a set Live does not name, because it empties the set. An agent needs an
  Option pick or your word. It holds Live while it runs (many short calls, a minute or more on the real rig).
- Mix 2's renders still start the arranger's own worker (`mixset.py worker`), which opens its own connection to Live.
  That is a known debt: it takes its turn only by Live's own limits, not by the app's lock. The render queue (INTEGRATION
  step 5) moves it into the app.

`zpkt app` starts the Song with the web adapter (`--adapters web,song`). `ZPKT_ARRANGER_DIR` names another arranger
folder; `ARRANGER_DATA` the data, as before.

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
