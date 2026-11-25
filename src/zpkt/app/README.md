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

## The MiniLab (the MIDI adapter)

`zpkt app --adapters web,midi` adds the MiniLab 3 as a hand of the app. It is off unless you name it. The old pager in
Live and ZpktMiniLabTempo stay the default until my gate (below), and the two must not run on one controller: to try
the adapter, set Live's MiniLab 3 control surface to None (so Live lets go of the ports) and stop the pager's hold.

It reads raw MIDI through mido (`uv sync --extra midi`), asks `zpkt.app.minilab.mapper` what each move means, and sends
the answer to the bus as `who = "minilab"`, so history, undo and the change stream cover it like the web. It sends
SysEx back: the display, the pad LEDs and the knob rings.

- **The map** is data in `contrib/mixdesk/pagercore.py` (`MINILAB_MAP`), the same file the pager loads in Live, so
  pickup, realign and the pages are one copy of the rules. The old `HARDWARE` table is as it was. The map is DESIGN 3b:
  Shift layer, octave buttons for pages (Shift: loop window), the data knob (turn for focus, push to reset, Shift to
  scrub the bar), Hold for latch, the mod strip and the keys for the focused control, pitch bend as hold-to-hear (up for
  Pin, down for Ref), and the transport buttons (Live no longer reads them). ZpktMiniLabTempo's job is the "tempo"
  layer: fader 4 as tempo, pads 7 and 8 halve and double it. It applies when the desk is not driving the MiniLab
  (`ZPKT_MIDI_TEMPO=auto`, the default; `on` and `off` force it).
- **The profile** is `lib/contracts/minilab3-profile.json`: every control, its message and its source. **Every item is
  unverified.** Some numbers were read from Live's installed MiniLab_3 script; the strips, Hold and the keys are the
  usual MIDI messages, assumed; the octave buttons have no known message, so they do nothing until you learn them with
  `zpkt app midi learn octave_up`. `ZPKT_MINILAB_PROFILE` names a corrected file, `ZPKT_MINILAB_PORT` the port.
- **Feel.** A knob's stream is coalesced: the latest place per control is kept and one `page.set` batch goes out per
  tick. `zpkt app midi latency` runs the adapter with a probe and prints the knob-to-Live timings. Run it only on the
  rig; it is the gate before the pager retires.
- **Live's changes** still reach the app through the pager's reports. The Remote Script also has a generic watch now
  (`zpkt.live.watch`, `zpkt.app.watching`): the app registers a page's keys and Live pushes each change on the same
  socket. It is built and tested on FakeLive and not turned on in `zpkt app` yet.

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
