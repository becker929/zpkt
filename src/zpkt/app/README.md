# zpkt.app

I want one interface for my techno toolkit, and one door to Live. This is the door.

Only `zpkt.app` talks to Live. Everyone else is a client of it: the phone, the desktop, the MiniLab, an agent, the
`zpkt` command, the booth. The app opens the connections once and hands them to `zpkt.live` and `zpkt.audio`, which
are libraries and never open one.

## How it fits

```
adapters        web · agents (Ask) · MiniLab · API (later)      turn what they hear into Commands
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

## Ask

Ask is the chat with Claude and Gemini, ported from Zpkt web (Node, :8789, which keeps running untouched). It is the
`agents` adapter, so it starts with `zpkt app` (`--adapters web,agents` is the default). The page is at `/app/ask/`.

- **Engines.** Claude Code runs as one `claude -p` process per turn. Gemini runs over ACP: one `gemini --acp`
  process, permission prompts you answer on the page (mode "Ask first"), and an estimated dollar cost for each turn.
  A session can change engine between turns: the other engine gets the turns it missed. Keys come only from the
  harness's secret lookup; nothing in Ask reads a key or a key file.
- **Sessions.** Every event is appended to a file as it happens, so a run goes on when the page closes, and any
  device can open the session and follow. Files are in Zpkt web's forms (`sessions.json`, `sessions/<id>.jsonl`,
  `library.json`, `surface-state.json`, `workspaces.json`) in `ZPKT_ASK_DIR` (default
  `~/_agent_scratch/zpkt-app/ask`). Point it at a copy of Zpkt web's data folder to carry its sessions over; old
  `zpkt-surface` blocks still draw.
- **Tools.** An agent has four tools and no others: make a page (checked against Live, saved only when clean), read
  the state, read the last measurement, propose an Option. They are app commands behind a small MCP server
  (`python -m zpkt.app.ask.mcp`) that calls `POST /app/ask/api/tool` with the session's token. The bus tags them
  `agent` and groups them by session. None moves Live, and an agent cannot name any other command.
- **Also ported.** The work view, cards and the preset library, the failure budget (it stops a run that keeps
  failing), project notes read to the agent and written after a turn (given a model to write with), attachments,
  and files an agent points at.
- **Not ported.** A card's Render, Grid and Pick buttons (`hands panel`), the fast path, purpose lines, "Improve this
  app", Reset Live, the password gate. The page hides what it cannot do.

`tests/app/test_ask_*.py` run it with a scripted provider and stand-ins for `claude` and `gemini --acp`. No model,
no key, no Live.

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
