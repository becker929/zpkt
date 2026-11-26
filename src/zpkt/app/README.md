# zpkt.app

I want one interface for my techno toolkit, and one door to Live. This is the door.

Only `zpkt.app` talks to Live. Everyone else is a client of it: the phone, the desktop, the MiniLab, an agent, the
`zpkt` command, the booth. The app opens the connections once and hands them to `zpkt.live` and `zpkt.audio`, which
are libraries and never open one.

## What is in it

`zpkt app` starts four adapters by default (`web,api,song,agents`; `midi` is off unless named). Where to look:

| Want | Where | Section |
|---|---|---|
| The Hear bar, the Desk, undo and history | `/app/` (`/` sends you here; the old desk page is at `/desk/`) | What it serves |
| Pages of controls, drawn and mapped to the MiniLab | `/app/` Desk; `zpkt page make` | Pages |
| Versions of the mix side by side | `/app/` Options tab | Options and the one render queue |
| The arrangement as lanes, Mix 1, transitions, Build in Live | `/app/` Song tab; the arranger under `/app/song` | The Song |
| Chat with Claude and Gemini | `/app/ask/` | Ask |
| The MiniLab 3 | `--adapters web,midi` | The MiniLab |
| The `zpkt` command, the booth, the demos | `127.0.0.1:8984`, `/api/v1/` | The API and its clients |

Every page has the same tab bar: Desk, Song, Options, Ask. It is at the bottom on a phone and at the top from 700 px
up. Ask is a tab like the others, at every width.

## How it fits

```
adapters        web · API · Ask (agents) · Song · MiniLab (off unless named)   turn what they hear into Commands
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
effect: `read`, `make` (pages, files, versions) or `move` (changes Live). One table, `effects.py`, says which, and
a command without a line there cannot be registered. The checks, in order:

- **who** must be one of the seven.
- **The agent rule.** An agent may read, make pages and propose Options. A `move` from an agent needs `approval`:
  `"user"` (you said so) or `"option:<id>"` (an Option was picked). Its changes always have a group, and the first
  change of a group saves a checkpoint first, so one undo takes the group back.
- **The wrong-set guard.** Every `move` is held to a set, and nothing is sent when Live has another open. The desk's
  moves are for the page's set; that answer is kept for five seconds. A job from the API is for the set its caller
  names (`expect_set`), or else for the set the app last saw open: the desk's at the start, then one the app opened
  or a caller named and Live had. Only opening a set is let through. A set Live does not name (unsaved) passes.
- **The lock.** Live takes one job at a time. A command that cannot get it in five seconds answers 503 and says Live
  is busy. It is never dropped silently.

Every applied move is a history entry with its `who` (and its group) and, once it settles, one `Change` per control
in the set's change stream (`zpkt.live.changes`, `GET /api/changes?since=N&who=agent`).

## What it serves

`zpkt app` (or `uv run python contrib/mixdesk/server.py`, which starts the same thing) serves the web on 8985 as the
mix desk always did (`MIXDESK_PORT`), with the pager's datagrams on 8986 and the meter on 8987. The API is a separate
port, 8984 (below). `ZPKT_DESK_URL` names the web server (pages, `/app/`), `ZPKT_APP_URL` the API.

- `/` sends you to `/app/` (a 302). The old desk page is at `/desk/`; all its routes, event shapes and ports are as they
  were.
- `/app/` is the new shell: the Hear bar (bar, spectrum from the meter, "N changed", what you hear, Play, Now / Pin /
  Ref, undo, redo, history) and the Desk. It reads the same state through `/events?app=1`.
- `/app/shell/<file>` serves what every page shares, from `static/shell/`: `shell.css` (the tokens, the tab bar, the
  loading line), `nav.js` (draws the tab bar), `controls.css` and `controls.js` (the panel: a page of controls as a
  map of the MiniLab, see Pages) and `listen.js` (the Listen button, when it is there). The folder is flat. Only `.css`, `.js`, `.json` and `.svg` files are served, and only by a plain file name.
- `POST /api/command` takes any command: `{"kind": "mix.set", "args": {"norms": [["Kick bus/volume", 0.4]]}}`.
  `GET /api/commands` lists them. The old `POST /api/...` paths are these commands under their old names.

The web server answers only for its own names: `localhost`, `127.0.0.1`, any `*.ts.net` name (the phone reaches the
desk through `tailscale serve`, which keeps the name the phone asked for) and the names in `ZPKT_APP_HOSTS` (comma
separated). Any other `Host` gets 403, reads included. That stops DNS rebinding: a page that points its own domain at
127.0.0.1. A write that carries an `Origin` header (a browser always sends one) must name the site asked for, by `Host` or by
the proxy's `X-Forwarded-Host` and `X-Forwarded-Proto` (`web.host_allowed`, `web.cross_site`). A write with no `Origin`
(curl, a script) needs a Bearer token from the app's token store, as on the API, or it gets 401. Programs should use
the API on 8984. Mounted routes (Ask, the Song) hold their own session tokens.

## The shell: one look, one tab bar, one way to wait

The look is the chat's: bone and black, one lime accent, a quiet ceramic card, and only the controls are physical.
`shell.css` holds the tokens under the names `app.html` and Ask already used (`--bg`, `--panel`, `--ink`, `--acc` ...).
A page links it and defines none of them itself.

- **The tab bar.** A page has `<nav id="tabs" data-current="desk|song|options|ask"></nav>` and loads `nav.js` right
  after it. On `/app/` Desk, Song and Options are buttons (`data-t`) and switch in place; Options is a sheet over the
  Desk or the Song. On any other page they are links to `/app/#desk`, `/app/#song` and `/app/#options`. Ask is always
  a link to `/app/ask/`. `window.zpktNav.set(name)` marks the current tab. `nav.js` writes `data-at` (`top` from
  700 px, else `bottom`) unless the page wrote it; the bar's parent must be a flex column.
- **Addresses.** `/app/` opens on `#desk`, `#song` or `#options`, and keeps the address in step as I switch.
  `/app/#page=<id>` opens the Desk on that saved Page. A Page that is saved but not on the desk gets a plain message.
- **Waiting.** A page change takes about a second: the command waits its turn for Live, the pager swaps what the
  MiniLab's controls mean, and only then does the `page` event come back. On the tap the button is marked
  (`is-waiting`), a lime line runs across the top of the desk area (`.loads.is-loading`), and the old controls dim and
  take no touch (anything with `data-stale` inside `.loads.is-pending`). The `page` event clears it. After 5 s, or when
  the command is refused, a line says the page did not change, with Retry. The line also runs while the Song is read
  and while it builds in Live. With reduced motion the line stands still.
- **Listen.** The Hear bar's bottom row has `<span id="listen"></span>`, and the page loads `/app/shell/listen.js` as
  a module. A missing file changes nothing.

`tests/app/test_shell_static.py` checks the route; `tests/app/test_shell_nav.py` checks the tabs, the addresses and
the waiting in WebKit.

## The API and its clients

`zpkt app` also starts the API adapter on 127.0.0.1:8984 (`ZPKT_API_PORT`). It is how the `zpkt` command, the booth and
the demo reach Live (docs/app-clients.md). Every call is a Command stamped `cli`, `booth`, `demo` or `agent`. The app
stamps it by the token the call carries, never by what the request says: each caller has its own token file in
`~/.config/zpkt/` (`app-token` for the cli, `app-token-booth`, `-demo`, `-agent`; mode 0600, made at start). `you` and
`minilab` are never accepted from the API. A coding agent in a terminal (`ZPKT_AGENT=1`) is `agent`, so its changes
need an Option you picked (`ZPKT_OPTION=<id>`). Which set a job is for, and the wrong-set check, are in `bus.py`
(`SetGuard.check_job`); whether a command is a read, a make or a move is in `effects.py`. The jobs are in `jobs.py`; the client in
`client.py` (standard library only, no Live code); the transport that lets a `LiveClient` caller switch in one line in
`zpkt.live.app_transport`. The web page is `you` and cannot run them. The shapes are `lib/contracts/app-api.schema.json`.

## Options and the one render queue

An Option is a set of Versions of the mix, made to be heard side by side. I look at them in the Options sheet of
`/app/` (the Options tab): a grid of Versions with their loudness and their gap to the base. Tapping one puts its
numbers and spectrum on the Hear bar. "Pick" puts a Version's values on the mix as one move, stamped `you`, which one
undo takes back.

There is one store of Options, `renders.py`'s. What an agent proposes (`options.propose`, older name `option.propose`: a title, a reason and its
moves, kept in `options.json` in the Ask folder) is listed there with the rendered ones, as an Option with one
Version. I pick it with the same button and the same command. My pick puts its moves on Now and marks it picked,
and only then may the agent's own command name it (`approval: "option:<id>"`). A proposal's values are raw numbers;
one given as text is listed but cannot be picked.

- `options.make` asks for one: `{"title": "Kick up", "versions": [{"label": "+3 dB", "writes": [["Kick bus/volume",
  0.8]]}], "range": {"start_beat": 64, "length_beats": 32}}`. The first Version is the mix as it stands (the base).
- `renders.py` is the worker. For each Version it writes the values, has Live export through `zpkt.live.export` with
  the app's connection, puts the values back (whatever happens), and hands the WAV to `zpkt.audio.measure`. Progress
  streams as `{"t": "option"}` messages ("rendering 2 of 3"). Live is held for one Version at a time.
- The queue is `renderqueue.py` (it came from `contrib/arranger/`, whose `renderqueue` is now an alias for it). Jobs
  are files under `<data>/options/jobs`, in the shape of `lib/contracts/option.schema.json`.
- Mix 2, the spectral fixes, the kick options and `zpkt live panel grid` (once `hands panel grid`) still render in
  their own tools, into their own folders. The app reads those and lists them as Options. It changes none of them, so
  the old pages work as before.
- `options.list`, `options.get`, `options.show` (reads) and `options.pick` (a move) are commands on the bus
  (`option.pick` is an older name for `options.pick`). An agent may make an Option. It needs your word or an Option pick
  to make a Version Now, and its use of one picked Option never picks another.

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

## Pages

A Page is what an agent writes for "I want to change this": groups of controls with a role and a weight, and no pixels
(`zpkt.live.page`). One renderer draws it, and the same spec gives the MiniLab its assignment.

**Every page of controls is one panel, and the panel is a map of the MiniLab 3** (Anthony's rule, 25 November 2026:
controller pages look like the controller). One renderer draws them all: a saved Page, the mix desk's own MiniLab
pages (`contrib/mixdesk/desk.json`) and a made surface.

- **All 20 slots are always drawn, each in its physical place**: knobs 1–4 over 5–8, the four faders to their right,
  the 8 pads in one row below. Where 8 columns of 44 px targets do not fit (the panel's own box is 440 px or less: a
  phone, and a 768 px tablet beside the Hear bar) it folds in half: knobs over pads 1–4, then faders over pads 5–8.
- **A mapped slot is a live control.** A knob or a fader is dragged up and down, or moved with the arrow keys; a
  pad is a key. It shows its label and its value. When a panel holds more than one group, each control has its
  group as a small caption, and neighbouring groups alternate a faint tint. A choice (a list of items) on a knob is
  a knob with stops.
- **An unmapped slot is drawn in the same place, greyed.** It takes no touch and says its hardware name ("Knob 6:
  not mapped"). A target the open set lacks keeps its slot, greyed, and says "not in this set". A macro is drawn in
  its slot but is turned on the MiniLab only.
- **A Page that needs more than one MiniLab page** has numbered buttons above the panel. On a phone (under 700 px) a
  sideways swipe on the panel goes to the next or the previous one. Both wait for Live like any page change (Waiting,
  above). The first 6 px of a touch decide whether it moves a control or is a swipe.
- **The look is the chat's**: a ceramic card, a machined knob with a lime arc, a fader in a slot, pads as keys. The
  drawing is `static/shell/controls.js` (`window.zpktControls`: `panel(slots, attrs)`, `slot(model)`, `set(el, n)`,
  `hwName(slot)`) and the styles are `static/shell/controls.css`, both served under `/app/shell/`. They are a copy of
  the chat's drawings in `static/ask/zpkt/`, with values as places 0 to 1. Any page can load them.

- `zpkt page make SPEC.json` (or `-` for standard input) sends the spec to the running app. `zpkt page lint` only
  checks it. The command goes to `POST /api/agent/command`, so the app stamps it `who=agent`; an agent can make pages
  but cannot move Live without approval.
- The linter is the gate. A rejected spec answers 422 with the reasons, nothing is saved, and the agent repairs it.
- A good one is saved as `<sets_dir>/pages/<set>/<id>.json` and as one made surface per MiniLab page, so the pager in
  Live and the old desk take it too. The commands are `page.make`, `page.lint` and `page.layout`; `GET /api/pages`
  lists the saved pages.
- "Make a surface" on the old desk calls `page.make`: it now asks Claude for a Page. An answer in the old slot form
  is still accepted.
- `/app/` draws a saved Page from `page.layout` (the rules are `zpkt.live.page_layout`). Its `panels` list has one
  panel per MiniLab page, each with all 20 slots in the hardware's order; a slot names its control (`ref`), group
  and tint, or only its hardware name. The desk's own pages have no layout: the shell builds the same slots from
  `/api/desk` and the values the pager reports.

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
  That is a known debt: it takes its turn only by Live's own limits, not by the app's lock. Moving it onto the app's render queue is open work.

`zpkt app` starts the Song with the web adapter (the default is `--adapters web,api,song,agents`). `ZPKT_ARRANGER_DIR` names another arranger
folder; `ARRANGER_DATA` the data, as before.

## Ask

Ask is the chat with Claude and Gemini, ported from Zpkt web (Node, :8789, which keeps running untouched). It is the
`agents` adapter, so it starts with `zpkt app` (it is in the default `--adapters web,api,song,agents`). The page is at `/app/ask/`.

- **Engines.** Claude Code runs as one `claude -p` process per turn. Gemini runs over ACP: one `gemini --acp`
  process, permission prompts you answer on the page (mode "Ask first"), and an estimated dollar cost for each turn.
  A session can change engine between turns: the other engine gets the turns it missed. Keys come only from the
  harness's secret lookup; nothing in Ask reads a key or a key file.
- **Sessions.** Every event is appended to a file as it happens, so a run goes on when the page closes, and any
  device can open the session and follow. Files are in Zpkt web's forms (`sessions.json`, `sessions/<id>.jsonl`,
  `library.json`, `surface-state.json`, `workspaces.json`) in `ZPKT_ASK_DIR` (default
  `~/_agent_scratch/zpkt-app/ask`). Point it at a copy of Zpkt web's data folder to carry its sessions over; old
  `zpkt-surface` blocks still draw.
- **Tools.** An agent has four tools and no others: make a page (the `page.draft` command, which takes the spec as `spec` and still accepts `page`: checked against Live,
  saved only when clean, not put on the desk; the fuller `page.make` is for you and the CLI), read
  the state (`desk.state`, older name `state.read`), read the last measurement, propose an Option (`options.propose`; a record in the Ask folder, `proposals.py`, held by the app's one
  store of Options and listed in the Options sheet, where I pick it). They are app commands behind a small MCP server
  (`python -m zpkt.app.ask.mcp`) that calls `POST /app/ask/api/tool` with the session's token. The bus tags them
  `agent` and groups them by session. None moves Live, and an agent cannot name any other command.
- **Also ported.** The work view, cards and the preset library, the failure budget (it stops a run that keeps
  failing), project notes read to the agent and written after a turn (given a model to write with), attachments,
  and files an agent points at.
- **Not ported.** A card's Render, Grid and Pick buttons (`zpkt live panel`), the fast path, purpose lines, "Improve this
  app", Reset Live, the password gate. The page hides what it cannot do.

`tests/app/test_ask_*.py` run it with a scripted provider and stand-ins for `claude` and `gemini --acp`. No model,
no key, no Live.

## Files that stay where they were

The desk's own files stay in `contrib/mixdesk/`: `desk.json`, `sources.json`, `pager.py` (it runs inside Live) and
the old page. `ZPKT_MIXDESK_DIR` names another folder. The old module names there (`history`, `protocol`, `deskstate`,
`surfaces`, `server`) are aliases for the modules here, so old imports and tests keep working.

## How to add an adapter

One seam puts an adapter's pages and routes on the web server: `desk.mounts` (`mounts.py`). A mount is a route set
under a path prefix, with one method, `handle(request)`. It gets GET, HEAD, POST, PUT, PATCH and DELETE as a `Request`
(method, path, the path after the prefix, query, a body reader, the connection) and answers a `MountReply`; a mount
that streams writes on the connection and returns None. Ask is mounted at `/app/ask` and the Song at `/app/song`. The
server's own checks (the Host name, writes from its own pages only) come before any mount.

1. Add a module to `zpkt/app/adapters/`, say `midi.py`.
2. In it, write a class with `name`, `start()` and `stop()`. Its constructor takes an `AppContext` (the bus, the desk
   and the settings).
3. End the module with `ADAPTER = AdapterSpec("midi", MidiAdapter)`.
4. Turn what it hears into `Command(kind, "minilab", args)` and call `context.bus.submit(...)`. That is all it may do
   to Live: an adapter imports nothing from `zpkt.live` (a test checks it).
5. Start it with `zpkt app --adapters web,midi`.

`adapters.discover()` finds every module that defines `ADAPTER`, so the core is not edited.

## How to test it

`uv run --all-extras pytest -q tests/app`. The tests use `FakeLive` (handed straight to the connections, no port), a fake meter socket
and free ports. They never touch the running desk, a MiniLab or the real Live. `make quick` is the everyday gate and runs all of it; `make check` adds contrib and prototypes.
