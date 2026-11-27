# zpkt.app

I want one interface for my techno toolkit, and one door to Live. This is the door.

Only `zpkt.app` talks to Live. Everyone else is a client of it: the phone, the desktop, the MiniLab, an agent, the
`zpkt` command, the booth. The app opens the connections once and hands them to `zpkt.live` and `zpkt.audio`, which
are libraries and never open one.

## What is in it

`zpkt app` starts four adapters by default (`web,api,agents,listen`; `midi` is off unless named). Where to look:

| Want | Where | Section |
|---|---|---|
| The Hear bar, the Desk, undo and history | `/app/` (`/` sends you here; the old desk page is at `/desk/`) | What it serves |
| Pages of controls, drawn and mapped to the MiniLab | `/app/` Desk; `zpkt page make` | Pages |
| Two or more settings of the same controls, to switch between while Live plays | pads on a Page | Pages (Compare) |
| The song in Live: tracks, arrangement clips, locators | `/app/` Song tab | The Song |
| A drum pattern on 16 pads, painted along its track | `/app/` Song tab: Steps and Paint | Steps |
| Chat with Claude and Gemini | `/app/ask/` | Ask |
| Live's sound in the browser | the Listen button; `/app/listen` | Listen |
| The MiniLab 3 | `--adapters web,midi` | The MiniLab |
| The `zpkt` command, the booth, the demos | `127.0.0.1:8984`, `/api/v1/` | The API and its clients |

Every page has the same tab bar: Desk, Song, Ask. It is at the bottom on a phone and at the top from 700 px
up. Ask is a tab like the others, at every width.

## How it fits

```
adapters        web · API · Ask (agents) · Song · Listen · MiniLab (off unless named)   turn what they hear into Commands
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
- **The agent rule.** An agent may read and make pages. A `move` from an agent needs `approval: "user"` (you said
  so), and the API never takes that word from an agent, so no call of an agent's moves Live. For a change it
  suggests, it makes a page with compare states (Pages, below); the press is yours. A move that does carry your
  word always has a group, and the first change of a group saves a checkpoint first, so one undo takes the group
  back.
- **The one move an agent makes itself: `live.change`** (Anthony, 26 November 2026: values and devices, "act, then
  undo"). It is a move like any other, held by the wrong-set guard and the lock, and it is the only command with
  `agent_may` in its `Spec` (`effects.AGENT_MAY`; `effects.py` has the reason, `tests/app/test_effects.py` writes
  the set out again). `mix.set`, `transport`, `live.run` and every other move are refused for an agent as before.
  The next section says what it does.
- **Ask first: `live.propose`** (the same decision: structure and code are "ask first"). A batch that may also
  remove a device, make a track or run code. An agent cannot send it on its own. In Ask its `propose_live` tool
  shows the batch as a card in the chat; after your tap on "Do it" the Ask gate sends `live.propose` with your
  word (`approval`), still as `agent`. It is in the next section too ("A batch that waits for your tap").
- **The wrong-set guard.** Every `move` is held to a set, and nothing is sent when Live has another open. The desk's
  moves are for the page's set; that answer is kept for five seconds. A job from the API is for the set its caller
  names (`expect_set`), or else for the set the app last saw open: the desk's at the start, then one the app opened
  or a caller named and Live had. Only opening a set is let through. A set Live does not name (unsaved) passes.
- **The lock.** Live takes one job at a time. A command that cannot get it in five seconds answers 503 and says Live
  is busy. It is never dropped silently.

Every applied move is a history entry with its `who` (and its group) and, once it settles, one `Change` per control
in the set's change stream (`zpkt.live.changes`, `GET /api/changes?since=N&who=agent`). Moves with one group are one
entry. So are changes to one control by one person (`you` or `minilab`), one after the other with nothing else in
between: a drag, then nudges, then more nudges are one row in History and one undo, back to where the control was
before the first. The step ends when another control is touched, a checkpoint is saved, something is undone, or 30
seconds pass without a change (`history.SAME_CONTROL_S`). A switch (a solo, a mute) is a step each time it is
thrown. An agent's changes join by group only. A step that grows after it reached the change stream gets the rest
of it there as one more `Change`.

## A batch of changes: `live.change`

`change.py`. One command carries a whole batch, so an agent spends one tool call on a request:

```json
{"why": "warmer kick", "steps": [
  {"set": "Kick bus/volume", "to": 0.8},
  {"add": "Saturator", "track": "Kick bus", "at": 0},
  {"set": "Kick bus/Saturator/Drive", "to": 6.0},
  {"device": "desk Glue", "track": "Kick bus", "on": false},
  {"move": "desk EQ", "track": "Kick bus", "to": 2}]}
```

- **Steps.** `set` writes a raw value to a state key (the keys and numbers `desk.state` gives; any key of the set,
  on a page or not). `add` loads an audio effect from Live's browser onto a track that exists, last or at `at`.
  `device` with `on` switches a device on or off (it is the value `<track>/<device>/Device On`). `move` puts a
  device at another index of its chain. A second device of a name is `Saturator#2`, as in state keys. There is no
  step that removes a device, makes a track, changes routing or clips, or runs code: those wait for your tap, and
  are `live.propose` (below). `use` runs an ability, code you allowed for good ("Abilities", below): it needs no
  tap, and undo does not take it back.
- **Checked whole, first.** Shape, limits (40 steps, 8 adds), the rails, then Live's own names and ranges: every
  track, device, effect name, range and step of a list. Any problem refuses the whole batch with 400 and `problems`,
  one plain sentence each, and nothing has changed: no value, no device, no checkpoint. A value on a device the
  same batch adds cannot be checked before the device exists; it is checked when its step comes.
- **The rails.** Never a monitor track (`mon ...`). Never Main's desk devices (`desk headroom`, `desk Glue`,
  `desk Utility`, `zpkt listen`, `zpkt desk meter`: `change.RAILED_ON_MAIN`). No device is added to or moved on
  Main: what sits there is heard under every monitor track too. Main's own volume and its other devices' values may
  be set. Only in the set the desk was opened on (the wrong-set guard).
- **Run in order, one short call each.** A checkpoint is saved first (`before-<group>-<time>`, by `sys`). Then each
  step is its own call to Live (a load is a few: find, load, read the chain). A step that fails stops the batch:
  the answer is 502 with `done`, `failed` (`step`, `what`, `why`) and `not_done`, and what was done is still one
  History row. The app's lock is held for the whole batch, so another command waits up to five seconds and is then
  told Live is busy; Live itself is never held longer than one step.
- **One History row, one undo.** The row is an entry of kind `change`: `why`, the value `moves` and the device
  steps in `devices` (`add` with the index it landed on, `move` with `from` and `to`). Undo writes the values
  back, then takes the device steps back last one first: an added device is deleted, a moved one goes back. Redo
  loads the device again and writes the values again. "Go back" to before such a row does the same as one step
  (`history.back`). A device that is no longer there is passed over and named in the reply's `notes`. Going back to
  a checkpoint (`history.revert`) puts values back only: a checkpoint holds no chain.
- **The answer is small**: `{"ok", "done", "undo": "warmer kick (3 controls, 2 devices)", "now": {key: [shown,
  raw]}, "added": [{"track", "device", "at"}]}`.
- **Anyone may send it.** The person's page and the cli can; the row then says `you` or `cli`. The page has no
  control for it.

The Live calls are in `zpkt.live.chain` (the load is the one `zpkt.live.mix` has used since October 2026) and
`zpkt.live.writes.set_keys`. Tests: `tests/app/test_live_change.py`.

### A batch that waits for your tap: `live.propose`

`propose.py`. Structure and code are asked first. The batch has the same shape, and a step is any `live.change`
step or one of three more:

```json
{"why": "parallel drive on the hats", "steps": [
  {"new_track": "return", "name": "Drive"},
  {"add": "Saturator", "track": "Drive"},
  {"set": "Hats bus/send Drive", "to": 0.6},
  {"remove": "desk Sat", "track": "Hats bus"},
  {"code": "find_track('hats').mute = False", "does": "Unmutes the hats channel."}]}
```

- **Steps.** `remove` takes a device off a chain. `new_track` makes an `audio`, `midi` or `return` track called
  `name`, last (a return gets Live's letter by itself); later steps may use it by name. `code` is Python for Live
  with `does`, one plain sentence that says what it does: for routing, clips and whatever else has no step. It
  runs as `live.run` does, the string as it is, in one call.
- **Two commands.** `live.propose.check` is a read: it checks the batch whole and answers with the card, `{"why",
  "steps": [{"n", "text", "no_undo", "code"}]}`, each step one short line in plain words ("Remove desk Sat from
  Hats bus", "New audio track: Parallel", "Set Kick bus volume to -3.0 dB": the value as Live would show it, from
  one short read; the raw number for a value on something the batch makes). `live.propose` is the move: it checks
  the batch whole again, saves a checkpoint and runs it, with `live.change`'s own machinery (`change.check`,
  `change.run`) and three more runners. It is for the API's callers, as `live.run` is: the web page may not send
  it, and an agent's needs your word.
- **Checked whole, first.** As `live.change`, plus: at most 3 code steps of 2,000 characters, each of which must
  parse; at most 8 new tracks, named in at most 40 characters with no `/`, and not by a name the set has; a
  device that an earlier step removes cannot be named again. Steps are checked against the set as it is, so no
  step may rely on what a code step makes. A problem is a 400 with every problem listed, and nobody is asked.
- **The rails.** `live.change`'s, and: no device is removed on Main, and no new track is named `mon ...` or
  `Main`. Code cannot be checked against the rails. It is screened for the names it spells out (a string that
  starts with `mon `, and `zpkt listen` and `zpkt desk meter`, the two devices that are only the desk's on Main):
  a guard against an accident, not a wall. You read the code on the card.
- **The tap** (`ask/tools.py`, `ask/permissions.py`). The Ask gate sends the check, shows the card through the
  permission desk (a `permission` event whose `tool` is the card, so every device shows it) and blocks the tool
  call for at most 4 minutes. Nothing of Live is held meanwhile: the bus takes every other command, and the web
  server answers every other request (each has a thread of its own). "Do it" sends `live.propose` with
  `approval: "user"` as `agent`. "Don't", no answer, or a stopped turn send nothing: the agent is told
  `{"ok": false, "declined": true}` or `{"ok": false, "unanswered": true}`. With no turn running there is nobody
  to ask (409). What came of it goes into the transcript as a `proposal` event (`state`: `done`, `failed` with
  `step`, `refused`, `declined`, `unanswered`, `stopped`), so the card shows it and keeps it.
- **The card** (`static/ask/index.html`). `why` as its title; each step on a line; a code step's `does` with the
  code under it in a small box that scrolls inside itself; "No undo" on each step that undo cannot take back;
  "Do it" and "Don't". After the answer it says what happened and ticks each step that ran.
- **One History row, and what undo leaves.** The row is an entry of kind `change`, as for `live.change`. Undo takes
  back its values, added devices and moves. It does NOT take back a removed device (its settings are gone), a new
  track, or code (the app cannot know what code did). Those are the entry's `stays`, each with its `words`. The
  row shows them ("no undo: 1 removed, 1 track, 1 code"), and undone it says "undone in part" (or "not undone"
  when nothing else was in it). The replies of `history.undo` and `history.back` name them in `left`. Code is
  kept as soon as it was sent, also when Live reported an error: part of it may have run, and the row says so.
  When a device is removed, the entry's earlier device steps are rewritten as if it had never been on the chain
  (`history.taken_out`) and the values the batch wrote to it are dropped, so undo cannot land on a namesake.
- **The answer** after "Do it": `{"ok", "approved": true, "done", "undo", "no_undo": [...], "now", "added",
  "removed", "made", "ran": [{"step", "ok", "result"}]}`; 502 with `failed` and `not_done` when a step failed;
  400 with `problems` when the set changed while the card waited (nothing changed).

The Live calls are `zpkt.live.chain.delete`, `zpkt.live.newtrack` and `zpkt.live.describe.shown_for`. Tests:
`tests/app/test_live_propose.py` (the check, the run, History, undo), `tests/app/test_propose_tool.py` (the wait)
and `tests/app/test_propose_page.py` (the card and the row).

### Abilities: code you allowed for good

`abilities.py` (the store and the rules), `coderun.py` (code made ready to send), `propose.py` and `change.py`
(the commands). Anthony, 26 November 2026: "an 'Always' button which adds the code to an auto allowed set, as new
abilities with documentation and everything, run the same as other tools", and "guide the agent to write functions
with clean parameters ... allow the agent to chain tools together so we build abstraction over time."

- **"Always".** The card of a proposal with at least one code step has a third button between "Do it" and
  "Don't". It does what "Do it" does, and keeps each code step that ran without an error as an ability. A step
  that failed or did not run is not kept. A proposal with no code step keeps two buttons, and so does one whose
  code would not fit (there are at most 50 abilities). The card then says what it kept, by name.
- **What an ability is.** A name, one sentence (`does`), parameters, and the code exactly as the card showed it:
  one JSON file, `<abilities_dir>/<name>.json` (`lib/contracts/ability.schema.json`), with `made`, `session`,
  `runs` and `last_run`. `abilities_dir` is a rig setting (default `<sets_dir>/abilities`, `ZPKT_ABILITIES_DIR`):
  an ability is code for Live in general, not for one set. The app never edits one in place.
- **Parameters.** A code step may carry `"name"` (snake_case), `"params"` (`{name: {"type": "number" | "integer" |
  "string" | "boolean", "description", "default"?, "enum"?}}`, at most 8) and `"args"`, this run's values. A
  parameter without a default is required. In the code the values are the dict `args`. A step with no name gets
  one made from `does`, which never takes another ability's place.
- **Arguments are data.** They are checked against the parameters at the proposal and at every run, the defaults
  are filled in, and they reach Live as a JSON literal that the first line of the call parses into `args`. No
  character of an argument is ever formatted into the code's text (`abilities.program`).
- **Replacing.** A code step named like an ability is a new version of it. Its card says "Replaces <name>" and how
  many abilities use it. "Do it" runs the new code once and leaves the kept one alone; only "Always" on that card
  replaces it, and from then on everything that uses it runs the new code. A replacement whose parameters no
  longer fit a written-out call in an ability that uses it is refused before anybody is asked.
- **Chaining.** In an ability's code, and in a proposal's, `use("other_ability", {...})` runs another ability and
  returns its `result`. The name must be written out, so the app can read what a piece of code uses (`ast`). It
  sends exactly those abilities along in the same one call (their code and parameters as part of the JSON
  literal) and defines `use` in front of the code: each ability used runs in a namespace of its own, with its own
  `args` and the same Live names, and its arguments are checked there too. Refused before anybody is asked: a
  name that is not written out, an ability that is not there, a circle, more than 5 uses deep, more than 12
  abilities in one call, and written-out arguments that do not fit. The card shows what a code step uses as
  chips; the list shows "uses" and "used by".
- **Running one: `ability.run {name, args}`.** No card and no wait: the tap on "Always" was the standing yes. It is
  the second command with `agent_may` (`effects.AGENT_MAY`), held by the wrong-set guard and the lock, for the
  API's callers (never the web page). One call to Live. The reply is `{"ok", "name", "result"}` (and `no_undo`),
  or 502 with the error and "part of the code may have run", 400 when the arguments or the rails say no (nothing
  ran), 404 when it is gone ("propose its code again").
- **History.** A run is one row (a `change` entry whose `why` is the call, `set_tempo(bpm=133)`) with a
  checkpoint before it, and its code is in the row's `stays`: undo does not take it back. An ability whose code,
  and all it uses, only reads (`zpkt.live.agent.only_reads`, the test `live.read` uses) leaves no row and no
  checkpoint.
- **As a step.** `{"use": "<name>", "args": {...}}` is a step of `live.change` and of `live.propose`. It is checked
  with the batch (the ability is there, the arguments fit, the rails) and runs in its place among the other
  steps. In `live.change` it needs no tap. At most 8 in a batch. History treats it as code ("no undo").
- **As a tool.** In Ask each ability is a tool of its own, `ability_<name>`: its description starts with `does`,
  then one line per parameter, and its input schema is made from the parameters (`ask/tools.py`). The MCP server
  lists the tools from the app (`GET /app/ask/api/tools`) and says when the list changed (`listChanged`: after
  every call, and every 5 seconds while it waits), so an ability kept in one turn is a tool at the latest in the
  next. `desk.state` (`read_state`) lists the abilities too, so an agent can look before it proposes.
- **Fewer, better ones.** The agent is told to write a code step as a function of its parameters, named verb_noun
  for what it does in general, to look at the abilities first, and to replace one that almost fits rather than
  add a second (the `propose_live` description, the agent's guide). Two checks help. A parameter that is declared
  and never read (`args["x"]`, `args.get("x")`) is a problem: 400, nobody is asked. `hints` are not: an ability
  whose name differs only by an ending or whose sentence is the same, and a track or device of the open set
  spelled out in code that has no text parameter. They go to the agent in the reply, never onto the card.
- **Seeing and removing them.** The Ask sheet (the clock button) has "Abilities": name, sentence, parameters with
  their defaults, runs, what each uses and is used by, the code behind the row, and a Remove key.
  `ability.remove {name}` is the person's only (the page and the command line; an agent gets 403). It is
  immediate: the tool is gone from the list and a call answers 404. The file is moved to `removed/` in the same
  folder. An ability that used it is marked "Broken: needs <name>" and answers so until that one is proposed
  again. `GET /app/ask/api/abilities` is the list as JSON and `GET /app/ask/api/abilities.md` the same as a page
  to read: what the agent may do on its own now.
- **The rails, said plainly.** An ability is the exact code you saw, run with new argument values. The screen of
  proposals applies when it is kept and at every run, to the code and to text arguments (a monitor track's name,
  `zpkt listen`, `zpkt desk meter`), also inside Live when one ability hands text to another. It is a guard
  against an accident, not a wall. Removing an ability is immediate.

Tests: `tests/app/test_abilities.py` (the bus), `tests/app/test_ability_tools.py` (the gate, the routes, the MCP
list) and `tests/app/test_ability_page.py` (the card and the sheet).

## What it serves

`zpkt app` (or `uv run python contrib/mixdesk/server.py`, which starts the same thing) serves the web on 8985 as the
mix desk always did (`MIXDESK_PORT`), with the pager's datagrams on 8986 and the meter on 8987. The API is a separate
port, 8984 (below). `ZPKT_DESK_URL` names the web server (pages, `/app/`), `ZPKT_APP_URL` the API.

- `/` sends you to `/app/` (a 302). The old desk page is at `/desk/`; all its routes, event shapes and ports are as they
  were.
- `/app/` is the new shell: the Hear bar and three tabs in one document, Desk, Song and Ask. It reads the same
  state through `/events?app=1`. Changing tabs loads nothing again, so the Hear bar, the transport and Listen stay
  as they are. `/app/ask/` (the chat's own page) goes on to `/app/#ask`.
- **The Hear bar** says which song is open and lets me play it and take changes back. Its top is the set's name
  and the level meter, and nothing else (Anthony, 26 November 2026: "bias toward removing unneeded things"). Then
  Play, solo and mute, the Listen button, undo, redo and History. Off the page since then: "bar N of M", the loop's
  bars, "Live", "N changed" with its checkpoint, the strip with the playhead, the spectrum, and the tempo and time
  signature (those two are on the Song tab). Their elements stay in the page, hidden by CSS, and the page still
  holds what they said (`S.state`, `S.hear`). The
  set, the tempo, the signature, the length, the loop's span and every track's solo and mute come with the pager's
  snapshot and its messages, so nothing asks Live for them. The level meter shows the peak of what Listen plays, in
  dB below full scale. `listen.js` sends it to the page as a `zpkt-listen` event. With Listen off the meter is
  hatched and says so ("Listen paused" when it was on on the page before, the button's own word). It reads samples
  and changes none.
- **The transport** is on the Hear bar, on every tab: Play (from where the playhead is; Pause keeps the place),
  Stop (stops and goes back to the start of what is played: the loop's start, or bar 1), and what loops, as three
  keys: All (the whole song), Start (its beginning) and Peak. A key sets Live's loop to that span and turns
  looping on; the lit key again turns it off. Set while Live plays inside the span, nothing is interrupted;
  outside it, the playhead goes to the span's start. The spans are the desk's own for its set
  (`pagercore.LOOPS`: whole, build, drop) and come with the pager's snapshot as `loops`; a span the set does not
  define is a key that cannot be pressed. The lit key says what loops; the Song tab draws the loop and the playhead.
  All of it is the `transport` command (`play`, `pause`, `stop`, `seek`, `loop`
  with `off`, `whole`, `build` or `drop`): a move of the transport, never a History row.
- **Solo and mute** are lit beside Play whenever a track is soloed or muted, by anyone, in Live or here. The pager
  listens to every track's solo and mute (never the monitor's own tracks) and sends the whole list on a change
  (`{"t": "flags"}`); the state holds it as `solo` and `mute`. Up to two tracks show by name, and a tap on a name
  clears it. More are a count that opens the list. Clearing is `mix.set` with the state key (`"Kick bus/solo"`):
  a History row and one undo, like any move. A solo thrown in Live is a History row too.
- **The spectrum** is off the page (26 November 2026), and so is its "Turn on" key. The command stays:
  `meter.install` puts the "zpkt desk meter" device on Main. It
  runs the desk's own tool (`meter.py` in the mixdesk folder) with the app's connection, as a job of its own,
  because Live's browser takes seconds to list a new device, and tells the page how it goes (`{"t": "meterjob"}`).
  It is one History row ("Spectrum off → on"), and undo takes the device off Main again. It
  never counts as a change.
- **The count of changes** is off the page too. The app still keeps it: it counts from the last checkpoint saved
  or gone back to (`history.base`), and is zero right after a save or a go back (`/api/hear`: `changed`, `base`).
  At a start the base is the last checkpoint on file. History shows the checkpoints. (The Pin and its commands are
  as they were; the count no longer follows it.)
- **Undo is an icon.** Its label for a screen reader says the control and the value it goes back to; nothing is
  written on the key. Redo is
  disabled when there is nothing to redo. The history's view has both steps (`undo`, `redo`: the id and, per
  control, its key, its place and Live's text). On the tap the page puts the controls there at once and the
  answer settles them, as for a control the hand moves. A going back (`history.revert`, `history.back`) tells the
  page where the controls go before Live is written (`{"t": "own"}`), for the same reason.
- **Nothing is made anew on an event.** The Hear bar's parts, the transport's buttons and the panel's controls are
  elements that stay: a value, the playhead and the level are moved in place (`controls.js`
  `update`), and a part is drawn again only when its own markup changes. Focus, a screen reader's place and a
  reference to an element survive Live's events.
- **Now, Pin and Ref are not on the page** (Anthony, 25 November 2026). The monitor's commands (`monitor.hear`,
  `monitor.pin`, `monitor.choose`) and the MiniLab's hold-to-hear stay.
- **History** lists every change with the control's name as the page shows it and its old and new value in Live's
  own units. From 1100 px it is docked in the right column, under the song's facts, so its rows fill while the
  knobs turn. Narrower, the clock button opens it as a sheet that takes no touch from the page behind: a tap
  outside closes it and still reaches the control. The rows are in strict time order, newest first: an undone
  change stays where it happened, greyed and marked, until a new change makes redo impossible, and a checkpoint
  sits above everything it holds. The list opens on this sitting (changes with no gap of 90 minutes); earlier
  ones are folded under their day, and there a change carries no "you". Every step in effect is a place to go
  back to: a tap on its row offers "Go back", which takes that step and every later one back as one new step
  (`history.back {entry}`), so undo reverses it. A checkpoint is a row with a flag and a "Go back" button: it puts
  the desk's controls back as one step (`history.revert`), so undo reverses it. A batch an agent made
  (`live.change`) is one row: who, its `why` in bold, and a count ("3 controls, 1 device"). A batch you said yes to
  (`live.propose`) also says what undo does not take back ("no undo: 1 removed, 1 track, 1 code"), and undone it is
  marked "undone in part". "Save checkpoint" takes a name, or uses the date and time, and shows
  "Saving" at once (`history.checkpoint` with `new: true`, which never overwrites: a taken name gets a number).
  Saving a checkpoint keeps what can be redone. Names a machine made ("start-20261125-1701") are shown as what they
  are ("Start of session, 25 Nov, 17:01").
- `/app/shell/<file>` serves what every page shares, from `static/shell/`: `shell.css` (the tokens, the tab bar, the
  loading line, the Ask tab's frame and mark), `nav.js` (draws the tab bar and shows Ask in place), `controls.css` and `controls.js` (the panel: a page of controls as a
  map of the MiniLab, see Pages), `steps.css` and `steps.js` (the step sequencer on the Song tab, see Steps) and `listen.js` (the Listen button, when it is there). The folder is flat. Only `.css`, `.js`, `.json` and `.svg` files are served, and only by a plain file name.
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

- **The tab bar.** A page has `<nav id="tabs" data-current="desk|song|ask"></nav>` and loads `nav.js` right
  after it. On `/app/` the three tabs are buttons (`data-t`) and switch in place. On any other page they are links
  to `/app/#desk`, `/app/#song` and `/app/#ask`. `window.zpktNav.set(name)` marks the current tab. `nav.js` writes
  `data-at` (`top` from 700 px, else `bottom`) unless the page wrote it; the bar's parent must be a flex column.
- **Ask in place.** `/app/` has `<div id="ask" hidden>` beside `#desk` and `#song`. The page's tab switch calls
  `window.zpktNav.ask(true)` for Ask and `ask(false)` for any other tab; `nav.js` does the rest. It puts the page
  `/app/ask/?embedded=1` in a frame there the first time Ask is shown and keeps it, so a running answer goes on
  arriving while the Desk shows. Hidden, the frame is only not seen (`visibility`), so it keeps its place in the
  conversation. The frame and `nav.js` talk with `postMessage` on the same origin: the chat says
  `{zpktAsk: {state: "busy" | "done" | "idle"}}` and `{zpktAsk: {go: "#page=<id>"}}`; the app says
  `{zpktAsk: "shown"}`. `go` sets the address in the app's own document, so a link in the chat opens the Desk, the
  Song or a Page with no reload.
- **The Ask tab's mark.** While another tab shows, the Ask tab carries `data-mark="busy"` (a grey ring) while the
  agent works and `data-mark="new"` (a lime dot) once it has answered. Showing Ask clears it. The tab's
  `aria-label` says the same.
- **A short view.** With Ask showing on a phone, when the view is under 600 px tall (the keyboard is up), `#app`
  gets the class `short` and the Hear bar keeps only its first row. Where the keyboard covers the page instead of
  resizing it (iOS), `nav.js` sets `#app` to the visible height (`visualViewport`), so the composer stays above the
  tab bar.
- **Addresses.** `/app/` opens on `#desk`, `#song` or `#ask`, and keeps the address in step as I switch. Any other
  address (an old link to `#options`) lands on the Desk.
  `/app/#page=<id>` opens the Desk on that saved Page. At once the desk shows that Page's title (from
  `GET /api/pages`) with "Loading", the loading line runs and the old controls dim; the address stays
  `#page=<id>` until that Page is the one on the desk. A Page that cannot be opened gets a plain message.
- **Waiting.** A page change takes about a second: the command waits its turn for Live, the pager swaps what the
  MiniLab's controls mean, and only then does the `page` event come back. On the tap the button is marked
  (`is-waiting`), a lime line runs across the top of the desk area (`.loads.is-loading`), and the old controls dim and
  take no touch (anything with `data-stale` inside `.loads.is-pending`). The `page` event clears it. After 5 s, or when
  the command is refused, a line says the page did not change, with Retry. The line also runs while the Song is read
  and while it builds in Live. With reduced motion the line stands still. The desk's title changes on the tap to
  the page asked for, with "Loading" beside it, and the Pages list marks that page and scrolls it into view.
- **Not an error.** With Live running and no MiniLab 3, the desk works. The page says "no MiniLab" in a quiet
  mark by the title and shows no red line. A Live that does not answer still gets the red line.
- **Listen.** The Hear bar's bottom row has `<span id="listen"></span>`, and the page loads `/app/shell/listen.js` as
  a module. A missing file changes nothing.

`tests/app/test_shell_static.py` checks the route; `tests/app/test_shell_nav.py` checks the tabs, the addresses and
the waiting in WebKit; `tests/app/test_ask_tab.py` checks Ask in place (the Hear bar and Listen stay, the mark, a
page link with no reload, the sizes). `tests/app/test_desk_touch.py` and `tests/app/test_desk_second_walk.py` are the two cold
walkthroughs' findings in WebKit (the second: solo and mute, one undo, return points, the build's set, the
spectrum's command, the base of the count of changes, History docked, round steps, the loading Page, the Song's ruler, elements
that stay); `tests/app/test_second_walk.py` holds the same rules below the page, with no browser.

## The API and its clients

`zpkt app` also starts the API adapter on 127.0.0.1:8984 (`ZPKT_API_PORT`). It is how the `zpkt` command, the booth and
the demo reach Live (docs/app-clients.md). Every call is a Command stamped `cli`, `booth`, `demo` or `agent`. The app
stamps it by the token the call carries, never by what the request says: each caller has its own token file in
`~/.config/zpkt/` (`app-token` for the cli, `app-token-booth`, `-demo`, `-agent`; mode 0600, made at start). `you` and
`minilab` are never accepted from the API. A coding agent in a terminal (`ZPKT_AGENT=1`) is `agent`: it reads and
makes pages (`zpkt page make`), may send `live.change`, and its other changes to Live are refused. Which set a job is for, and the wrong-set check, are in `bus.py`
(`SetGuard.check_job`); whether a command is a read, a make or a move is in `effects.py`. The jobs are in `jobs.py`; the client in
`client.py` (standard library only, no Live code); the transport that lets a `LiveClient` caller switch in one line in
`zpkt.live.app_transport`. The web page is `you` and cannot run them. The shapes are `lib/contracts/app-api.schema.json`.

## The render queue

There is no Options tab and no list of rendered Versions any more (Anthony: "we don't want grid search"). Live's
output streams to the browser (Listen), so two settings are compared by switching Live itself while it plays:
compare states on a Page (Pages, Compare). The `options.*` commands, `/api/options` and the agent's
`propose_option` are gone, and with them `approval: "option:<id>"` and `ZPKT_OPTION`.

What is left is the queue itself, `renderqueue.py`: one request file per batch in a folder. It came from
`contrib/arranger/`, whose `renderqueue` is an alias for it, and mix 2's worker (`mixset.py worker`) is its only
user now. Mix 2, the spectral fixes, the kick options and `zpkt live panel grid` render in their own tools, into
their own folders, and are heard on their own pages. Folders an older app wrote (`<data>/options`, `options.json`
in the Ask folder) are left where they are; nothing reads them.

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

### Steps on the MiniLab

While the step sequencer has a pattern in hand (the focus, `steps.focus`) and no clip is in its way, the MiniLab's
pads are that pattern's steps. The moment the focus clears, every control is the armed page's again. For the desk
itself the rule stays "pages, never pad banks": the two banks differ only in this layer.

| Control | In the layer | Command, as `minilab` |
|---|---|---|
| Pad bank A, pads 1-8 | steps 1-8 of the bar in view; lit when on | `steps.toggle` |
| Pad bank B, pads 1-8 | steps 9-16 | `steps.toggle` |
| Knob 1 | velocity of a new step, 1-127 | `steps.focus {velocity}` |
| Knob 2 | length in steps: 0.25, 0.5, 1, 2, 4 ... up to the pattern's length | `steps.focus {length}` |
| Knob 3 | swing, 0 to 0.75 | `steps.focus {swing}` |
| The data knob, turned | the next or previous sound of the kit (it wraps); a push does what it did | `steps.focus {pitch}` |
| A key | plays its sound as always, and chooses it | `steps.focus {pitch}` |
| Knobs 4-8, the faders | the armed page's, as always | |

The decisions are in `contrib/mixdesk/pagercore.py` (`steps_layer`, `pad_step`, `length_ladder`, `step_knob_value`,
`step_sound`), shared by both ways the controller reaches the app:

- **The pager in Live** (the rig's way). `zpkt.app.steps_minilab` is the app's side. When the focus changes, its
  thread tells the pager what to show in one short call (`m.DESK.steps_layer(...)`: on or off, the 16 lights, the
  three knob values), and only when something shown has changed; a toggle from the page never waits for the
  controller's lights. A light is told at once; a knob value changed on the screen is told when the changes have
  stopped for a moment. The pager reports a press as `{"t": "step", "pad": 0-15}`, a knob as `{"t": "step_knob"}`
  and a sound as `{"t": "step_sound"}` (a `turn` of the data knob, or the `pitch` of the pad selected in the
  track's Drum Rack). The hand turns them into the commands above, in order, from its own thread; turns that
  arrive while a command is in Live become one command with the latest of each. A pad's light flips under the
  finger, and when Live refuses the press the pager is told its lights again. A pager that was loaded before it
  had this layer (the app updated under it) is loaded again, once, when the app finds that out.
- **Keys choose the sound without being taken from the instrument.** The pager listens to
  `view.selected_drum_pad` of the track's Drum Rack while the layer is on. Guess: with the rack's Auto Select on,
  Live selects the pad a played note lands on. If Live does not, or the track has no Drum Rack, the data knob and
  the page still choose the sound. Playing the pad that is selected already changes nothing.
- **The MIDI adapter** has the same layer as the "steps" layer of `MINILAB_MAP`. It comes before the tempo layer
  and Shift for the controls it names. A key that is one of the kit's sounds chooses it, in any octave; the pad
  LEDs, the knob rings and the display (the sound's name) follow the focus.
- **The screen follows the controller** by the message it gets for any hand: `{"t": "steps", "focus", "edit"}`.
- **What the pager sends a pad and a knob** is what Live 12's own MiniLab_3 script sends them, read from the
  installed script: a pad's colour as `send_value(red, green, blue)` (its LED's SysEx message), and a knob's place
  as the script's realign message. The compare pads' lights go the same way now. None of it has been seen on the
  hardware yet.

`contrib/mixdesk/tests/test_pager_steps.py` plays the layer on the fake controller, `tests/app/test_steps_minilab.py`
the pager with the app behind it, and `tests/app/test_midi_steps.py` the adapter.

## Pages

**The word.** To the person these are **surfaces** ("Surfaces", "surface 3 / 15", "made a surface"): that is the
only word the pages of the app and the agent's answers use (Anthony, 26 November 2026). "Page" stays the technical
term: in the code, the commands (`page.make`, `page.organize`), the files, the addresses (`#page=<id>`) and these
docs. "MiniLab page" is the controller's own paging and keeps its name where it must be said.

A Page is what an agent writes for "I want to change this": groups of controls with a role and a weight, and no pixels
(`zpkt.live.page`). One renderer draws it, and the same spec gives the MiniLab its assignment.

**Every page of controls is one panel, and the panel is a map of the MiniLab 3** (Anthony's rule, 25 November 2026:
controller pages look like the controller). One renderer draws them all: a saved Page, the mix desk's own MiniLab
pages (`contrib/mixdesk/desk.json`) and a made surface.

- **Monitor is a tab** (26 November 2026; `#monitor`, `renderMonitor`): the live meter's bands drawn as a curve, 20 Hz
  to 20 kHz. While the song plays the page keeps a running mean (in power, about the last 40 meter messages) for
  whichever of A, B and C is heard, so each has a curve once it has been listened to; the one heard now is the
  thick one. Under it a table: each one's level and five bands (Sub, Low, Mid, High, Air), B and C as the difference
  from A. Three keys choose how the one heard now is drawn (`#monmode`, kept as `zpkt.mon`): Live (the newest
  reading of every band, moved toward at the screen's rate; the meter sends ten readings a second), Smooth (about a
  second) and Average (about four seconds, each band evened out against its neighbours). The others, and the table,
  always use the four-second mean. The curves are kept in the page only: a reload starts them again. With the meter off it shows the one
  action that turns it on (`meter.install`).
- **The reference loops over its own bars, and the switch is on the beat.** Each reference in `sources.json` says
  its own tempo and how many whole bars of its own its cut holds, from a downbeat (`"bpm"`, `"bars"`;
  `desk.reference_grids`). Hearing C loops those bars (with no such entry: the file's length) and puts the playhead
  at the same bar after the drop and the same place in the bar, counted in the reference's bars, so the beat goes
  on across the switch although the tempos differ; leaving C finds that bar and place in the mix again and brings
  back the loop that was on. The solo, the loop and the playhead go to Live as one call (`Monitor.place`,
  `monitor_tracks.placed_beat`): a call takes Live a few hundred milliseconds to get to, so the switch is heard
  that much after the press, but nothing is heard in between. It does not wait for the next bar line: the app
  cannot time a call into Live that finely.
- **Ask is dense** (26 November 2026, `static/ask/zpkt/dense.css`): Anthony chose "3 Extreme" of five renders on his
  own chat. 12 px text edge to edge, no air between blocks, your message as one bold line, the composer in one row;
  about twice the chat fits a phone. The file loads last and only makes things smaller. The keys that decide
  something (Do it, Don't, Stop, send) keep a size a thumb hits; rows that only unfold detail are 18 px.
- **After the phone walk** (26 November 2026): on the Song a tap on a lane chooses its track, and a strip under the
  lanes names it with a Solo and a Mute key (`#songsel`, `mix.set` on `TRACK/solo` and `TRACK/mute`); a tap on the
  lit B of a checkpoint lets the pin go (`monitor.pin` with `clear`); Play, Stop and the A / B / C keys pulse from
  the press until Live has answered (`asked`); in the list one tap on a row's number types it; the version saved
  before a batch reads "Before the assistant's change" or "Before a batch" (`cpLabel`).
- **Compare is in the play bar** (26 November 2026): the keys A, B and C (`#abc`, `monitor.hear` now, pin, ref). A is
  the mix now, B the pinned mix, C the reference. History has a B key on each checkpoint (`monitor.pin` with `name`)
  that chooses it as the pinned mix; until one is chosen B is the mix as the desk first saw it.
- **Labels are for a phone** (26 November 2026). A group's caption is written once over its run of slots, without
  what every group of the panel starts with ("Before fuzz: "). The page's head is the surface's title and nothing
  else: no readout of the control in hand, no caption, no "on MiniLab" chip, no count of surfaces ("Loading" shows
  there while a page is on its way). A switch in the pager (`#viewsw`, kept in `localStorage` as `zpkt.view`) shows the same slots as
  a **list**: a row per mapped knob and fader with its number on the controller, its group and name in full and its
  value, moved sideways; unmapped slots are left out and the pads stay keys. The map is the default. Where the
  larger text does not fit on a phone, the rows with nothing mapped give up their room (`.lean`), then the map shows
  one face at a time, and only then is the text made small (`.dense`).
- **All 20 slots are always drawn, each in its physical place**: knobs 1–4 over 5–8, the four faders to their right,
  the 8 pads in one row below. Where 8 columns of 44 px targets do not fit (the panel's own box is 440 px or less: a
  phone, and a 768 px tablet beside the Hear bar) it folds in half: knobs over pads 1–4, then faders over pads 5–8.
- **Nothing scrolls** (Anthony, 25 November 2026: "This app must have zero scrolling"). The Desk has no scroll:
  the title, the paging row and the whole map are on screen at every size from 360 x 640 up. The map takes the
  height that is left and its controls give way down to 44 px (`controls.css`); the page measures it (`fitPanel`)
  and, when the comfortable sizes do not fit, puts labels on one line (`.tight`). Where a folded map still does not
  fit (a phone), the rows and blocks with nothing mapped are left out (`.lean`), so a surface's knobs, pads and
  faders share one screen whenever they can. Only if that does not fit either it shows one face at a time: the
  knobs over pads 1 to 4, or the faders over pads 5 to 8, with a
  two-key switch in the paging row. A page with compare states opens on the face with its pads.
- **Lists that can grow are paged, never scrolled.** History shows as many rows as its box holds, newest first,
  with "newer" and "older" under it ("1–8 / 43"); a new change brings the newest rows back. The list of Pages in
  the side column shows the part with the page in view and has its own before and after. More than two soloed or
  muted tracks open as a list of five at a time. The Hear column and the side column have no scroll of their own.
- **The Song fits too.** Its lanes take the height that is left and give way down to 14 px each; past that they
  show a part at a time ("1–6 / 15") with the ruler over every part (`fitSong`).
- **The organizer** (the list key in the paging row and over the side list) is a sheet with two lists, Desk and
  Archived, paged to its height. A row is a surface: its thumbnail (the MiniLab's map, small, the mapped slots of
  its first MiniLab page lit, its pad number on the corner), its name, and on the Desk list earlier and later
  keys. The thumbnail is also the handle: dragged, the row follows, the place it would land is marked, and letting
  go moves it there (`move` with `to`). A tap on the name shows what can be done with that one: Rename (a field in
  the row), Archive; in the archive Restore and, for a made surface, Delete, which first turns the row into the
  confirm (its map, its name, Delete). Archive all and Restore all are over the lists. Every action is one
  `page.organize` command. `tests/app/test_organize_page.py` checks it in WebKit.
- **An empty desk** (every page archived) is a state, not a fault: the map is drawn with all 20 slots quiet and
  the title row holds the one way to a surface, a key that goes to Ask. The transport, History and the Song go on
  working.
- **The paging row** (under 1100 px; wider, the list of Pages is the side column) is the last row of the Desk:
  the page before, "13 / 15", the page after, and the face switch. One step is one MiniLab page, and the count is
  of MiniLab pages: a surface that takes two is two steps under one title, and has no buttons of its own.
  `tests/app/test_zero_scroll.py` checks all of it at six sizes.
- **A mapped slot is a live control.** A pad is a key. A knob or a fader is dragged up and down. The drag is
  relative: the control moves from where it is, never jumps to the pointer, and 200 px take it across its range.
  A mouse moves it from the first pixel. A finger has 4 px to say whether it drags or swipes, and its travel
  counts from where it came down. Shift, or a slow hand (under about 40 px a second), makes fine steps. Where the
  page knows the scale as numbers the value lands on round units: a drag on tenths of a dB (three figures for Hz
  and ms). A click gives it the keyboard: the arrows step a dB control by 0.5 dB (Shift: 0.1 dB; Page Up and Down:
  3 dB), a frequency by a semitone (Shift: a tenth of one; Page: an octave), a choice by one stop, and a control
  with no numbers by a hundredth of its range (Shift: a five-hundredth; Page: a tenth); Home and End go to its
  ends. The number under the control is the place to type: it is underlined, a click on it (or Enter, or a double
  click on the control) opens a field there, Enter commits and Escape cancels. A typed value that is no number
  flashes the old one. The page reads values off straight lines between 33 of Live's texts, so on a scale that is
  not linear in its unit a round value is Live's nearest (it shows its own text once it answers). It shows its
  label and its value. When a panel holds more than one group, each control has its group as a small
  caption, and neighbouring groups alternate a faint tint. A choice (a list of items) on a knob is a knob with stops.
- **The number follows the hand.** The page shows a control's new place and number at once, with a small turning
  mark, and counts it in "N changed". It reads the number from the control's scale: `mix.describe` hands over, once
  per control and kept per set, the items of a switch or list, or Live's text at 33 places along a continuous
  range, and the page reads between two of them off a straight line. A control with no scale shows its place as a
  percentage. One `mix.set` is in the air per control; the newest place waits and older ones are dropped, so a slow
  Live never queues a drag up. `mix.set` asks Live only to write (a control's range is kept after the first ask).
  When the last send is answered, Live's own text replaces the page's. If Live settled somewhere else, the number
  flashes. A refused move puts the control back.
- **An unmapped slot is drawn in the same place, faint, with no caption.** It takes no touch. Its hardware name
  ("Knob 6: not mapped") is there for a screen reader and on hover. A target the open set lacks keeps its slot,
  greyed, and says "not in this set". A macro is drawn in its slot but is turned on the MiniLab only.
- **A Page that needs more than one MiniLab page** is reached with the paging row's before and after. On a phone
  (under 700 px) a
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
  Live and the old desk take it too. The commands are `page.make`, `page.lint`, `page.layout`, `page.list`,
  `page.organize` (rename, reorder, move, archive, restore, `archive_all`, `restore_all`, or delete an archived
  made page; it writes `_organize.json` and reloads the pager, keeping the armed page where it can; a move, so the
  person's act and never an agent's; an empty desk is allowed; a deleted page's files go to "removed" folders)
  and `page.open` (open a saved page by id);
  `GET /api/pages` lists the saved pages and `GET /api/organize` lists every page unit (active and archived).
- "Make a surface" on the old desk calls `page.make`: it now asks Claude for a Page. An answer in the old slot form
  is still accepted.
- `/app/` draws a saved Page from `page.layout` (the rules are `zpkt.live.page_layout`). Its `panels` list has one
  panel per MiniLab page, each with all 20 slots in the hardware's order; a slot names its control (`ref`), group
  and tint, or only its hardware name. The desk's own pages have no layout: the shell builds the same slots from
  `/api/desk` and the values the pager reports.

### Compare

A Page can carry compare states: 2 to 8 named settings of the same controls, to switch between while Live plays and
Listen is on. This is how alternatives are tried; there is no other feature for it.

```json
{"title": "Kick: hotter?",
 "groups": [{"name": "Kick", "controls": [{"target": "Kick bus/volume"}, {"target": "Kick bus/desk EQ/1 Gain A"}]}],
 "compare": {"name": "Kick", "states": [
   {"name": "as it is"},
   {"name": "hotter", "writes": [{"target": "Kick bus/volume", "to": 0.8},
                                 {"target": "Kick bus/desk EQ/1 Gain A", "to": 0.7}]}]}}
```

- **A write** is `{target, to}`: a state key and the raw value, as `desk.state` gives it (`r`). A target need not be
  a control of the page. A state that names no writes, or leaves a target out, takes the value that target had
  when the page was first made. The app keeps those values in the saved page (`compare.baseline`, with each
  target's range in `compare.ranges`), across every later version of the page, so there is always a way back.
- **The linter** checks the targets and the raw ranges against the open set like any control: 2 to 8 states, names
  of at most 10 characters and no two alike, at most 24 values, a switch or a list on a whole number, no two
  states with the same values. A state that leaves a target out is an error only when no value of it was kept.
- **One pad per state**, in the pads row of the map: the last pads, in order (three states are pads 6, 7 and 8), on
  every MiniLab page of the Page. The page's switches take the pads before them. The pads of the set stand on one
  rail and each has a small lamp. On a phone the pads are scrolled into sight when the page opens.
- **A press** (`page.compare {id, state}`) writes every value of the state in one call to Live, as one move by
  `you`: one History row ("Kick, as it is → hotter, 2 controls") and one undo. The page lights the pad and moves
  the knobs for those targets on the press, before Live answers, by the same path as a dragged knob.
- **The lit pad is derived, never stored.** A pad is lit exactly when every one of its targets holds its value: a
  switch or a list exactly, a continuous value within a thousandth of its range (`zpkt.live.page.lit`; the page
  and the pager hold the same rule). Turn one of those knobs and no pad is lit; turn it back and it is lit again.
- **The MiniLab.** While such a page is armed, its state pads (both banks) do not arm pages: the pager reports the
  press (`{"t": "pad"}`), the app does the same `page.compare` as `minilab`, and the pager lights the pad of the
  state that is on from Live's own values. The other pads arm their pages as always, and so does the big encoder.
  With the MIDI adapter the map sends `page.compare` itself and the LEDs are SysEx. Tested on the fake controller
  only: whether the pad's light shows on the real MiniLab 3 is not known.
- **An agent** makes such a page with `make_page`, and changes one it made by sending the whole spec again with its
  `id`: the saved page is written over, and where it is on the desk it is redrawn in place (the surfaces keep their
  files and their place, the pager loads once, the desk stays on the page it was on). No value of the mix moves and
  no History row is written: `page.compare` is a move, so an agent cannot press. `desk.state` says, for each such
  page on the desk, its states and which is on.

`tests/live/test_page.py` holds the model and the linter, `tests/app/test_compare.py` the press, the undo, the
derived state, the agent's make and update and the fake MiniLab's pad, and `tests/app/test_compare_page.py` the
page in WebKit.

## The Song

- **The Song tab is the song in Live** (Anthony, 26 November 2026): one lane per
  track of the open set that has a region, and per MIDI track also when it is empty (never the monitor's own; an
  audio track with no regions is not drawn), its
  Arrangement clips as regions with Live's names and colours
  (a muted clip or track is dimmed), under a bar ruler with the locators as named spans, Live's loop and its
  bars, and Live's playhead. The ruler's left cell says the tempo and the time signature ("160 · 4/4"). Session
  clips are never read. The lanes have no buttons; what changes the song is Steps and Paint (the next part).
  `arrangement.read` is the one read
  (`Desk.arrangement`: one short call into the pager, `m.DESK.arrangement()`, and one for the MIDI tracks,
  `zpkt.live.steps.midi_tracks`): `{set, bars, beats_per_bar, tracks:
  [{id, name, color, muted, midi, drum_rack, regions: [{id, start, end, name, color, muted}]}], locators: [{beat,
  name}]}`, starts and ends in beats. It is kept until the pager says a clip, a track or a locator changed (`{"t":
  "arr"}`, from listeners on every track's arrangement clips, on the list of tracks and on the locators; the app
  says so itself after a step command made or deleted a clip, since the pager reports at most three changes a
  second), and the page reads again then. A region is an element
  of its own with an id that holds while it stays where it is (`t3@16`: track 3, from beat 16).
  `tests/app/test_song_live.py` checks the read and the page.
- The arranger (`contrib/arranger`, its own server on :8975) is a separate tool and is no part of the app any
  more: the Song adapter, its mount at `/app/song`, the `song.*` commands (`song.build` among them) and `set.open`
  were removed on 26 November 2026. Its render queue is still `zpkt.app.renderqueue` (below).

## Steps: a pattern on the Song, painted along the track

Anthony, 26 November 2026: "a feature ... which allows me to program midi using a step sequencer that works with my
midi controller and then allows me to paint that loop in the arrangement." It lives in the Song tab, drums first.
A pattern is an Arrangement MIDI clip of 1, 2 or 4 bars on a MIDI track (`zpkt.live.steps`; never a Session clip).
The page makes no sound: a tap writes a note into Live's clip, and Live plays it.

- **Getting in.** A MIDI track has a lane also when it is empty. Choosing it adds two keys to the strip under the
  lanes: Steps and Paint. With no MIDI track in the set the Song has one key, "Drum track": it opens a list of the
  Drum Rack presets Live's browser offers (a page of them at a time), and a tap on one makes a MIDI track called
  "Drums" ("Drums 2" where there is one) in front of the first monitor track, loads the kit and opens Steps on it.
- **Steps** takes the lanes' place. Row one: the track, the pattern's length (1, 2 or 4 bars), a loop key and the
  way out. Row two: the pattern before, "Bar N", the pattern after, and for 2 or 4 bars which bar of the pattern is
  on the pads. It opens on the loop's first bar, else on the bar under the playhead. Then the overview, a row per
  sound of the kit with 16 cells for the bar in hand: a tap on a row chooses the sound. As many rows show as the
  height holds (8 at most); the part of the kit with the chosen sound is the one in view. A track with no Drum
  Rack has a row for each pitch that has a note, and for C1 to G1 when it has none.
- **The panel** is laid out as the MiniLab. Its head: the sound, keys to the sound before and after, Clear and
  Paint. Three knobs (the Desk's own drawing, `controls.js`; a hand moves one up and down, 200 px across its
  range, Shift for fine; the arrow keys step it): Velocity and Length change the step touched last (it carries a
  dot; `steps.set`) and are what the next steps get; Swing rewrites the pattern (`steps.write`). Then "pads A",
  steps 1 to 8, and "pads B", steps 9 to 16: the MiniLab's two pad banks. A pad is lit when its step is on (paler
  under velocity 80), the beats have a dark edge, and the step under Live's playhead is outlined while Live plays
  inside the pattern. A tap lights the pad at once and sends `steps.toggle`; Live's answer settles it; a refusal
  puts it back and the toast says why. Clear empties the chosen sound's row; the key then reads "All" for three
  seconds, and pressed again it empties the pattern.
- **Clips in the way.** The Live side never cuts, shortens or moves a clip. A bar that a clip of another length
  lies over is a state of the bar row: "Bar N" is hatched red and the pads are off. Changing the pattern's length
  makes its own clip that long (`steps.write` with `from_bars`) when nothing else is in the way.
- **The loop key** sets Live's loop to the pattern's bars (`steps.loop`), follows the pattern in hand, and the lit
  key again, or leaving Steps, puts the loop back as it was.
- **Paint** is on the lanes. The chosen MIDI lane grows to 52 px and shows one cell per pattern length across the
  song, counted from the pattern's own bar: lime where the clip there hashes as the pattern in hand
  (`steps.read`'s `hash` and `painted`), grey where another clip of that length is, hatched where clips are in
  the way, and a dark edge on the pattern's own bar. A tap or a drag across cells paints them, one `steps.paint`
  a gesture (64 bars at most); with Erase lit the same gesture is `steps.erase`. The strip shows the pattern small,
  the track, and Steps, Erase and Paint (lit: a tap ends painting). The ruler, the loop and the playhead stay.
- **Nothing scrolls**, at 375 x 812, 390 x 664 and 1200 x 800; keys are 44 px, the pads 38 px or more on a phone.

The commands are `steps_commands.py`. The reads are anyone's; the others are moves, so the bus holds them to the
page's set and the lock and refuses them from an agent. None reads or writes a monitor track ("mon ...").

| Command | Arguments | Answer |
|---|---|---|
| `steps.tracks` (read) | | `tracks: [{name, index, color, drum_rack}]` |
| `steps.sounds` (read) | `track` | `sounds: [{pitch, name}]` (a Drum Rack's filled pads) |
| `steps.read` (read) | `track, bar, bars, steps_per_bar?, swing?, total_bars?` | `pattern` (a row per sound), `sounds`, `drum_rack`, `clip`, `blocked`, `off_grid`, `hash`, `beats_per_bar`, `painted: [{bar, hash, name}]`, `total_bars` |
| `steps.kits` (read) | `fresh?` | `kits: [name]` (60 at most; asked of Live once and kept) |
| `steps.toggle` | `track, bar, bars, pitch, step, velocity?, length?, swing?` | `on, velocity, created, entry` |
| `steps.set` | `track, bar, bars, pitch, step, velocity?, length?, swing?` | `on, velocity, length, entry` |
| `steps.write` | `track, bar, pattern, from_bars?` | what `steps.read` gives of the span, `created`, `entry` |
| `steps.paint` | `track, from_bar, bars, to: [bars], total_bars?` | `painted, skipped, replaced, clips, entry` |
| `steps.erase` | `track, bars: [bars], length, total_bars?` | `erased, skipped, clips, entry` |
| `steps.new_track` | `name, kit` | `track, index, kit, device, no_undo, entry` |
| `steps.focus` | `track, bar, bars, pitch, velocity?, length?, swing?, view?, name?`; a part of it; `{}` | `focus` |
| `steps.loop` | `bar, bars`, or `was` | `was: {on, start, length}` |

Clips in the way, a step with no note and a paint with no clip to paint from answer 409 with the reason (and
`blocked`); nothing has changed. A page may send `src`, a word of its own, with any of them: it comes back in the
`steps` message, so the page knows its own changes.

- **The focus** is what the sequencer has in hand, kept in the desk (`Desk.steps_focus`; `state.steps` in
  `/api/state` and every `full` message; `steps` in the agents' `desk.state`) and pushed to every page and adapter
  (`desk.push`, so the MIDI adapter's queue gets it): `{"t": "steps", "focus": {...} | null, "src"?, "edit"?}`
  (`protocol.StepsMessage`, `lib/contracts/mixdesk-message.schema.json`). The focus is `{track, bar, bars,
  steps_per_bar, view, pitch, name, velocity, length, swing, steps, blocked, rev}`: `steps` is the chosen sound's
  steps over the whole pattern (0, or the note's velocity), `view` the bar of the pattern on the pads (from 0),
  `rev` counts its changes. So pad k (0 to 15; A is 0 to 7, B 8 to 15) is lit when `steps[view * steps_per_bar +
  k]` is not 0, and a press of it is `steps.toggle {track, bar, bars, pitch, step: view * steps_per_bar + k,
  velocity, length, swing}`. The page sets the focus when Steps opens and when the sound, the bar or a knob
  changes, and clears it when Steps closes. Every command that changes a pattern keeps `steps` true (a toggle with
  no further call to Live) and sends the message with `edit: {track, bar, bars, what}`: a page reads a pattern
  again when another hand changed it, and takes up a focus another hand moved on its pattern (another sound,
  other values). The MiniLab's mapping starts from this: "Steps on the MiniLab", under The MiniLab above.
- **Undo.** Every changing command is one History row, an entry of kind `steps` (`history.py`): the track, what
  was done (`edit`, `length`, `paint`, `erase`, `track`), how often, and per span of the Arrangement what it held
  before (no clip, or the clip's name and notes). Undo puts each span back (`zpkt.live.steps.restore`, last one
  first) and keeps what it found there, so redo is the same act in the other order; "Go back" carries the spans
  too. Edits of one pattern by one hand within five seconds of each other are one row (`history.STEPS_RUN_S`). A
  span that cannot be put back (clips are in the way now) is left alone and named in the reply's `notes`. A new
  drum track is not undone: its row says "no undo: 1 track". `steps.loop` and `steps.focus` leave no row.
- **Swing** is not in Live's notes. The app keeps the swing each pattern was last written with while it runs
  (`Desk.steps_swing`), so a read puts the late steps where they are; after a restart a pattern swung by more
  than a quarter step reads with those notes off the grid (`off_grid`) until Swing is set again.
- **Not seen on the real Live yet**: which browser entries are kits, loading one, and where a new track lands
  (GUESS in `zpkt.live.steps` and `zpkt.live.inlive.steps`).

The page's code and styles are `static/shell/steps.js` and `steps.css` (`window.zpktSteps`: `open`, `close`,
`render`, `click`, `message`, `live`, and for the Song `songKeys`, `newKey`, `painting`, `lane`, `songSel`).
Tests: `tests/app/test_steps_bus.py` (every command, the rails, History and undo, the focus) and
`tests/app/test_steps_page.py` (WebKit); the Live side in `tests/live/test_steps.py`.

## Ask

Ask is the chat with Claude and Gemini, ported from Zpkt web (Node, :8789, which keeps running untouched). It is the
`agents` adapter, so it starts with `zpkt app` (it is in the default `--adapters web,api,agents,listen`). It is
the Ask tab of `/app/` (`/app/#ask`); its page and API are under `/app/ask/`.

- **Engines.** Claude Code runs as one `claude -p` process per turn. Gemini runs over ACP: one `gemini --acp`
  process and an estimated dollar cost for each turn.
  A session can change engine between turns: the other engine gets the turns it missed. Keys come only from the
  harness's secret lookup; nothing in Ask reads a key or a key file.
- **One long conversation.** Each workspace has one main conversation that goes on for good.
  `GET /app/ask/api/main?workspace=<id>` returns it and makes it on first use: empty, titled "Ask". Older sessions
  are never taken for it. They are the archive: `GET /app/ask/api/archive` lists them and their streams still read.
  The main conversation cannot be deleted. (Until 26 November 2026 the most recent old session became the main one.
  On its next start the store puts such an adopted session back in the archive, once: `SessionStore._fresh_mains`.)
- **Modes.** A producer has one mode, `auto`, and no menu: full power (Anthony, 26 November 2026). The agent has the
  shell, file edits, every tool and the app's seven tools (and the abilities). For Claude Code that is `--permission-mode auto` (Claude
  Code decides what is safe; nothing is disallowed and the Mac's other MCP servers are there); for Gemini it is
  `yolo`, and a question it still asks is answered yes. The default models are `claude-opus-5-5` and `gemini-4-neon`
  (`CLAUDE_AGENT_MODEL` and `GEMINI_AGENT_MODEL` override them). The careful mode `build` is still there: the app's
  tools (`change_live` too) and reading files only (`--permission-mode dontAsk`, `--allowedTools mcp__zpkt,Read,Glob,Grep`,
  `--disallowedTools Bash,Edit,Write,NotebookEdit,EnterPlanMode,ExitPlanMode`, `--strict-mcp-config`; never plan
  mode: there it described a page instead of making it). `/app/ask/?dev=1` shows a mode menu (remembered on the
  device; `?dev=0` hides it again): "Full", "Surfaces" (`build`), "Ask first" (Gemini asks on the page before an
  edit or a command), and under "Developer", "Edit files" and "No checks". The table is in `ask/engines.py`.
- **Paging.** `GET /app/ask/api/sessions/<id>/events?turns=20` gives the last 20 turns, `first`, `next` and `more`.
  Add `&before=<first>` for the turns before. Follow new events with the stream from `next`.
- **Compaction.** Before a turn, the app estimates the conversation in tokens (characters / 4). Past the engine's
  budget (Claude 100,000, Gemini 200,000; `ZPKT_ASK_COMPACT_TOKENS=120000` or `claude=120000,gemini=300000`, 0 is
  never) it compacts. The engine writes a summary of the older turns: what you want, decisions, pages made, open
  questions, the project. The last 3 turns stay word for word. Every engine then starts afresh on the summary and
  those turns (Claude with a new session id, Gemini with a new ACP session). The transcript gains a `compacting`
  event and then a `compacted` event with `summary`, `keep_from`, `turns`, `tokens` and `pages`. The file on disk is
  never cut. If the summary fails or takes over 3 minutes, the event says `failed` and the turn goes on with the
  last turns only. Your message is never lost. The rules are in `ask/compaction.py`.
- **Tools.** An agent has seven tools and no others: make or change a page (`page.draft`), read the state
  (`desk.state`, older name `state.read`, which also lists `units` with their ids and pads), read the last
  measurement, bounce audio and measure it (`bounce_audio` and `measure_audio`, next), change Live (`change_live`, the command `live.change`: a batch of value and device steps in one
  call, above), and propose a change that waits for my tap (`propose_live`, the commands `live.propose.check` and
  `live.propose`: a batch that may remove a device, make a track or run code, above). It cannot organize pages: order and archive are the person's. When I want to try an alternative it makes
  a page with compare states, or changes the one it made (Pages, Compare), and links to it.
  They are app commands behind a small MCP server (`python -m zpkt.app.ask.mcp`) that calls
  `POST /app/ask/api/tool` with the session's token. The bus tags them `agent` and groups them by session. Only
  `change_live` moves Live on the agent's own word, `propose_live` moves it after my tap, an ability
  (`ability_<name>`, one tool each: "Abilities", above) runs code I allowed for good, and an agent cannot name
  any other command. A `propose_live` call may take 4 minutes (the wait for the tap), so the MCP server gives that
  tool 5 (`mcp.timeout_for`), and `bounce_audio` the same for its exports; Gemini CLI gives an MCP call 10.
- **An agent's shell is bounded** (Anthony, 27 November 2026, after a search of the whole home folder ran for
  minutes: "Why aren't its executions bound in time?"). A shell command ends after 60 seconds for both engines
  (`engines.SHELL_LIMIT_S`). Claude Code gets it as its own limit (`BASH_DEFAULT_TIMEOUT_MS`,
  `BASH_MAX_TIMEOUT_MS`). Gemini CLI only limits how long a command is quiet, so the app sets that to the same
  number in a settings file of its own (`gemini-settings.json` beside the usage file, named to Gemini by
  `GEMINI_CLI_SYSTEM_SETTINGS_PATH`) and also ends what a command started when it is still running at the limit
  (`gemini.to_cut`: the processes under Gemini's that began after the command did, never the app's tool server);
  Gemini reports the command as ended and goes on. The agent's PATH starts with the app's own bin folder, so
  `zpkt audio` and a Python with `zpkt.audio` are found; the guide tells it to use those, not a script of its own.
  On the page, a turn the person stopped keeps its tool calls open (it has no answer to read instead), and
  Gemini's result for such a turn says `stopped`, not `success`.
- **Bounce and measure: how an agent hears** (Anthony, 26 November 2026: "The agent thinks it can't run a render.
  It should know how to bounce tracks and projects. And efficiently access the results without pulling them fully
  into context."; `bounce_commands.py`). `bounce_audio` (the command `render.bounce`) renders the mix, or up to
  four tracks, groups or returns, over a range of bars through Live's Export dialog: `what` ("mix", a name, a
  list) and `bars` ("loop", "song", or `[first, last]` counted from 1 with both included; default the loop when
  on, else the song). Each file is a 24-bit WAV in `<renders_dir>/bounce` with a small `.json` beside it (what,
  bars, tempo). The answer never holds audio: per file the path and a short sheet of about twenty numbers
  (`zpkt.audio.brief`: LUFS, true peak, peak, RMS, crest, the Monitor's five bands as parts of the RMS, and the
  stereo correlation and width). `measure_audio` (`render.measure`, a read) gives one more view of one window per
  call: `detail` "summary", "spectrum" (third octaves) or "over_time" (RMS and peak per bar, grouped to at most
  64 steps), a window in `bars` or `seconds`, and `against` for the difference to a second bounce (the same bars)
  or a reference by its id (whole). With no `file` it lists the bounces kept. The agent plays a bounce to me with
  an `audio` block.

  | | |
  |---|---|
  | Who may | `render.bounce` is a move an agent may ask for on its own (`effects.AGENT_MAY`); the page's set only |
  | What it costs | about 13 s a file and 0.1 s per second of audio; at most 4 files and 600 s of audio a call; the tool may take 5 minutes (`Tool.takes_s`) |
  | What it changes | no value of the mix, no History row, no version. Playback stops. Now is heard for it: a heard reference is left (`was_hearing`), a heard Pin comes back. The loop comes back; the time selection is the range bounced |
  | What it never does | bounce a monitor track (`mon ...`), un-solo or un-mute anything (it names `soloed` tracks and marks a `silent` file) |
  | What is kept | the newest bounces up to 2 GB (`KEEP_BYTES`); older ones go, each with its `.json` |

- **Live only through the app.** Ask's agents have a shell, and `ZPKT_AGENT=1` is set in it. With that set, every
  `zpkt live` (or `hands`) command that changes Live stops before it does anything and names `change_live` and
  `propose_live`:
  `exec` of code that is not certainly a read, `state put`, `device load`, `panel`, `open`, `save`, `export`,
  `modals --reap`, `rig reset`, `rig output NAME`, with or without `--direct` or `ZPKT_LIVE_VIA=direct`
  (`zpkt.live.cli_options.agent_stop`; `tests/app/test_agent_shell_guard.py`). Reads still run. This is a guard
  against accidents, not a security boundary: an agent with a shell can unset the variable, write its own socket
  client, or drive Live's window.
- **Links, not widgets.** An agent does not draw controls in the chat. It calls `make_page` and puts the reply's
  link in its answer: `[Title](/app/#page=<id>)`. `page.draft` takes the spec as `spec` (and still `page`), checks
  it against Live, and saves it only when clean, where `GET /api/pages` lists it. It does not put a new page on
  the desk; a page it changes (the spec has its `id`) is redrawn where it already is.
  Opening the link is my act: `/app/#page=<id>` sends the command `page.open {id}`, a move. That arms the page if it
  is on the desk already. Otherwise it first puts it on the desk and the MiniLab, as `page.make` does.
- **The page.** Ask is a tab inside `/app/`: the app shows the page `/app/ask/` in a frame (The shell, Ask in
  place). In the frame (`window.self !== window.top`, or `?embedded=1`) the page has no tab bar, title or Listen
  button of its own: the app's are the only ones. The button for earlier chats and the folder sits with the
  composer's tools. A link to `/app/` (`#page=<id>`, `#desk`, `#song`) is handed to the app, which changes tab with
  no reload; a link to any other page of the app replaces the app, never the frame. Opened by itself, `/app/ask/`
  goes on to `/app/#ask`. `/app/ask/?bare=1` is the page alone, with its own header, tab bar (three plain links if
  the shell's file does not load) and Listen button: the tests use it, and it is the fallback. It opens the
  folder's main conversation: the last 20 turns, then the stream. Reaching the top fetches the 20 turns before. An
  earlier chat is read-only, and its title shows in a header.
- **Before anything is said** the page shows four example requests and nothing else. A tap puts one in the box;
  sending is my own act.
- **Quiet by default.** While a turn runs, the bar above the box shows a pulse, what the agent is doing and the
  seconds so far. A finished turn's steps fold under one row, "Details": the counts of steps and tool calls and any
  error the agent recovered from are inside it. Under the answer are the seconds (a clock) and the cost (a price
  tag and the amount, titled "Cost"). A turn that failed
  says so once, in one sentence with what to do; the engine's own words are behind "Details".
- **What the page draws.** A `compacted` event is a quiet divider, "Earlier conversation summarised", that opens to
  the summary. A link to `/app/#page=<id>` is a card: the saved Page's title (`GET /api/pages`; the link's words
  until it answers, or when there is no such page), a small still map of the MiniLab (the slots the
  page uses are lit, the pads of its compare states too, the rest grey; it asks `page.layout`), and "Open on the Desk". With no such page it is the
  title alone. An `audio` block is a player. An old `zpkt-surface` block or `surface` event is a stub that says to
  ask for a page; the rendered files of its A/B are plain players.
- **Also ported.** The work view, the failure budget (it stops a run that keeps failing), project notes read to the
  agent and written after a turn (given a model to write with), attachments, and files an agent points at.
- **Not ported, or removed.** Controls drawn in the chat, their MIDI arming, saved card values and the preset
  library are gone (page code and routes): controls live on the Desk. Also not here: `zpkt live panel` renders, the
  fast path, purpose lines, "Improve this app", Reset Live, the password gate.

`tests/app/test_ask_*.py` run it with a scripted provider and stand-ins for `claude` and `gemini --acp`. No model,
no key, no Live.

## Listen

Listen plays what Live is playing, in the browser. It is for when I am away from the Mac. It is the `listen`
adapter, mounted at `/app/listen`, and it starts with `zpkt app`. Starting it only mounts the routes.

- **The button.** `/app/shell/listen.js` draws one button into `<span id="listen"></span>`: headphones, with a small
  tick that moves when sound arrives. Sound starts only from a tap. A tap on a greyed button says why it cannot play.
  The choice is kept in the browser. Changing tabs inside `/app/` (Desk, Song, Ask) does not stop it. Loading
  another document does (a reload, a sketch page): the button is then paused (a dashed ring and a dot; its label and the page's level meter both say
  "Listen paused") and the first tap anywhere on the
  new page starts it again.
- **Where the sound comes from.** Two captures, tried in this order. `GET /app/listen/status` says which one is in
  use as `source`: `live device` or `screen capture`. `ZPKT_LISTEN_SOURCE` chooses: `auto` (the default: the device,
  then the screen capture), `device` or `screen`. Either runs only while somebody listens and stops five seconds
  after the last listener leaves.
- **First: the Live device.** A Max for Live device, "zpkt listen", sits last on Main and sends Live's own samples to
  the app (`listen/device.py` reads it through `zpkt.live.listen`). Put it there once with
  `.venv/bin/python contrib/mixdesk/listen.py install`. It passes the audio through untouched and sends only while
  asked. It sends at Live's sample rate (44.1 kHz on the rig). It needs no macOS permission. The app listens on
  localhost TCP 8988 for the device and sends it `/listen 1` and `/listen 0` on UDP 8989; the sockets are opened in
  `connections.py` and only while a capture runs. When a capture starts, the device gets about 1.5 seconds to connect
  and say its rate. If it does not (it is not on Main, Live is not running, or Live has no audio output device
  selected, so its clock stands still), the ports are freed and the screen capture is tried. A capture ends when the
  device has been gone for four seconds, and the hub starts a new one.
- **Fallback: the screen capture.** `listen/capture.swift` records Live's output with ScreenCaptureKit and writes raw
  PCM at 48 kHz. No audio driver is installed. It is compiled on first use (about a second) into
  `<data_dir>/cache/listen` (`ZPKT_LISTEN_DIR` names another folder); no binary is in the repo. macOS must allow
  Screen & System Audio Recording (System Settings, Privacy & Security) for the app that started zpkt: the terminal,
  or the Claude app when an agent started it. macOS gives that app one such capture at a time. A second one (another
  copy of `zpkt app`, a run of the tool by hand) cuts the first off; the hub starts its capture again and the page
  reconnects, so I hear a short gap.
- **When neither works** the button is greyed and a tap says why, with the fix for each: put the device on Main and
  see that Live has an audio output device; or allow the recording, naming the app.
- **The sample rate is the capture's.** Nothing is resampled. The status gives it as `format.rate`, and
  `stream.pcm` gives it in its `X-Audio-Format` header (`s16le;rate=44100;channels=2`). The page reads it there and
  opens its audio output at that rate. A browser that will not open at that rate plays the MP3 stream. When a capture
  has to start again and comes back at another rate (the device left and the screen capture took over), the
  listeners are ended and their pages connect again at the new rate.
- **The streams.** `GET /app/listen/stream.pcm` is 16-bit little-endian stereo. The page reads it with a streamed
  `fetch` and plays it through an AudioWorklet that keeps about 70 ms in hand and throws away old sound when it
  falls behind (more than 220 ms). Each time the buffer runs dry it keeps a little more, up to 250 ms.
  `GET /app/listen/stream.mp3` is the same sound through ffmpeg for an `<audio>` element. The page uses it where the
  worklet cannot run (a page not served over HTTPS, an old browser). It is several seconds late.
  `GET /app/listen/status` says `available`, the `reason` if not, `listeners`, `capturing`, the `source` and the
  `format`.
- **Nothing is processed.** The page plays Live's samples as they are: no EQ, no effects, no gain. Loudness is the
  phone's own volume. This is playback, within the sound rule (`contrib/docs/sound.md`).
- **Measured** on the rig (25 November 2026). The Live device hands sound over about 12 ms after Live played it, at
  44.1 kHz. The screen capture hands it over after about 50 ms (68 ms at worst) and its tool uses under 1 % of one
  core. The page holds 50 to 100 ms on top of either (headless WebKit on the Mac itself), before the phone's own
  output delay and the network. The device and the page have not been measured together, and an iPhone over the
  tailnet is not measured yet.

`tests/app/test_listen.py` runs the adapter with a made-up capture, and the device's capture against a stand-in device
on free ports; `test_listen_page.py` taps the button in WebKit, at 48 kHz and at 44.1 kHz. The reader of the device is tested
in `tests/live/test_listen.py`.

## Files that stay where they were

The desk's own files stay in `contrib/mixdesk/`: `desk.json`, `sources.json`, `pager.py` (it runs inside Live) and
the old page. `ZPKT_MIXDESK_DIR` names another folder. The old module names there (`history`, `protocol`, `deskstate`,
`surfaces`, `server`) are aliases for the modules here, so old imports and tests keep working.

## How to add an adapter

One seam puts an adapter's pages and routes on the web server: `desk.mounts` (`mounts.py`). A mount is a route set
under a path prefix, with one method, `handle(request)`. It gets GET, HEAD, POST, PUT, PATCH and DELETE as a `Request`
(method, path, the path after the prefix, query, a body reader, the connection) and answers a `MountReply`; a mount
that streams writes on the connection and returns None. Ask is mounted at `/app/ask` and Listen at `/app/listen`. The
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
