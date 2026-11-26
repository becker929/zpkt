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

## What it serves

`zpkt app` (or `uv run python contrib/mixdesk/server.py`, which starts the same thing) serves the web on 8985 as the
mix desk always did (`MIXDESK_PORT`), with the pager's datagrams on 8986 and the meter on 8987. The API is a separate
port, 8984 (below). `ZPKT_DESK_URL` names the web server (pages, `/app/`), `ZPKT_APP_URL` the API.

- `/` sends you to `/app/` (a 302). The old desk page is at `/desk/`; all its routes, event shapes and ports are as they
  were.
- `/app/` is the new shell: the Hear bar and three tabs in one document, Desk, Song and Ask. It reads the same
  state through `/events?app=1`. Changing tabs loads nothing again, so the Hear bar, the transport and Listen stay
  as they are. `/app/ask/` (the chat's own page) goes on to `/app/#ask`.
- **The Hear bar** says which song is open and lets me play it and take changes back. From the top: the set's
  name, its tempo and time signature; "bar N of M", the loop as the bars it spans ("17–40", also drawn on the
  playhead's line; that is why the bar jumps back), "Live", and "N changed" with the checkpoint it counts from; the
  playhead; the spectrum; the level meter. Then Play, solo and mute, the Listen button, undo, redo and History. The
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
  define is a key that cannot be pressed. The strip under the song's facts shows the whole length, the spans, the
  one that loops and the playhead. All of it is the `transport` command (`play`, `pause`, `stop`, `seek`, `loop`
  with `off`, `whole`, `build` or `drop`): a move of the transport, never a History row.
- **Solo and mute** are lit beside Play whenever a track is soloed or muted, by anyone, in Live or here. The pager
  listens to every track's solo and mute (never the monitor's own tracks) and sends the whole list on a change
  (`{"t": "flags"}`); the state holds it as `solo` and `mute`. Up to two tracks show by name, and a tap on a name
  clears it. More are a count that opens the list. Clearing is `mix.set` with the state key (`"Kick bus/solo"`):
  a History row and one undo, like any move. A solo thrown in Live is a History row too.
- **The spectrum** is drawn from the "zpkt desk meter" device on Main. When no meter message has come for three
  seconds and the pager says the device is not on Main, its place holds one action, "Turn on" (`meter.install`). It
  runs the desk's own tool (`meter.py` in the mixdesk folder) with the app's connection, as a job of its own,
  because Live's browser takes seconds to list a new device. The page shows "Turning on", then the bars, or
  "Failed" with Retry. It is one History row ("Spectrum off → on"), and undo takes the device off Main again. It
  never counts in "N changed". With no data and nothing to press (Live is not there), the place is empty.
- **"N changed"** counts from the last checkpoint saved or gone back to (`history.base`), and says its name. It is
  zero right after a save or a go back. At a start it is the last checkpoint on file. A tap on it brings History
  forward. (The Pin and its commands are as they were; the count no longer follows it.)
- **Undo says what it does.** The button carries the control's label and the value it goes back to, and Redo is
  disabled when there is nothing to redo. The history's view has both steps (`undo`, `redo`: the id and, per
  control, its key, its place and Live's text). On the tap the page puts the controls there at once and the
  answer settles them, as for a control the hand moves. A going back (`history.revert`, `history.back`) tells the
  page where the controls go before Live is written (`{"t": "own"}`), for the same reason.
- **Nothing is made anew on an event.** The Hear bar's parts, the transport's buttons and the panel's controls are
  elements that stay: a value, the playhead, the spectrum and the level are moved in place (`controls.js`
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
  the desk's controls back as one step (`history.revert`), so undo reverses it. "Save checkpoint" takes a name, or uses the date and time, and shows
  "Saving" at once (`history.checkpoint` with `new: true`, which never overwrites: a taken name gets a number).
  Saving a checkpoint keeps what can be redone. Names a machine made ("start-20261125-1701") are shown as what they
  are ("Start of session, 25 Nov, 17:01").
- `/app/shell/<file>` serves what every page shares, from `static/shell/`: `shell.css` (the tokens, the tab bar, the
  loading line, the Ask tab's frame and mark), `nav.js` (draws the tab bar and shows Ask in place), `controls.css` and `controls.js` (the panel: a page of controls as a
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
spectrum's action, the base of "N changed", History docked, round steps, the loading Page, the Song's ruler, elements
that stay); `tests/app/test_second_walk.py` holds the same rules below the page, with no browser.

## The API and its clients

`zpkt app` also starts the API adapter on 127.0.0.1:8984 (`ZPKT_API_PORT`). It is how the `zpkt` command, the booth and
the demo reach Live (docs/app-clients.md). Every call is a Command stamped `cli`, `booth`, `demo` or `agent`. The app
stamps it by the token the call carries, never by what the request says: each caller has its own token file in
`~/.config/zpkt/` (`app-token` for the cli, `app-token-booth`, `-demo`, `-agent`; mode 0600, made at start). `you` and
`minilab` are never accepted from the API. A coding agent in a terminal (`ZPKT_AGENT=1`) is `agent`: it reads and
makes pages (`zpkt page make`), and its changes to Live are refused. Which set a job is for, and the wrong-set check, are in `bus.py`
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

## Pages

A Page is what an agent writes for "I want to change this": groups of controls with a role and a weight, and no pixels
(`zpkt.live.page`). One renderer draws it, and the same spec gives the MiniLab its assignment.

**Every page of controls is one panel, and the panel is a map of the MiniLab 3** (Anthony's rule, 25 November 2026:
controller pages look like the controller). One renderer draws them all: a saved Page, the mix desk's own MiniLab
pages (`contrib/mixdesk/desk.json`) and a made surface.

- **All 20 slots are always drawn, each in its physical place**: knobs 1–4 over 5–8, the four faders to their right,
  the 8 pads in one row below. Where 8 columns of 44 px targets do not fit (the panel's own box is 440 px or less: a
  phone, and a 768 px tablet beside the Hear bar) it folds in half: knobs over pads 1–4, then faders over pads 5–8.
- **Nothing scrolls** (Anthony, 25 November 2026: "This app must have zero scrolling"). The Desk has no scroll:
  the title, the paging row and the whole map are on screen at every size from 360 x 640 up. The map takes the
  height that is left and its controls give way down to 44 px (`controls.css`); the page measures it (`fitPanel`)
  and, when the comfortable sizes do not fit, puts labels on one line (`.tight`). Where a folded map still does not
  fit (a phone), it shows one face at a time: the knobs over pads 1 to 4, or the faders over pads 5 to 8, with a
  two-key switch in the paging row. A page with compare states opens on the face with its pads. On a phone under
  720 px tall the Hear bar keeps the song's facts and the playhead; the spectrum and the level give the Desk room.
- **Lists that can grow are paged, never scrolled.** History shows as many rows as its box holds, newest first,
  with "newer" and "older" under it ("1–8 / 43"); a new change brings the newest rows back. The list of Pages in
  the side column shows the part with the page in view and has its own before and after. More than two soloed or
  muted tracks open as a list of five at a time. The Hear column and the side column have no scroll of their own.
- **The Song fits too.** Its lanes take the height that is left and give way down to 14 px each; past that they
  show a part at a time ("1–6 / 15") with the ruler over every part (`fitSong`).
- **The paging row** (under 1100 px; wider, the list of Pages is the side column) is the last row of the Desk:
  the page before, "13 / 15", the page after, and the face switch. The numbered buttons of a Page with more than
  one MiniLab page are at the right of the title. `tests/app/test_zero_scroll.py` checks all of it at six sizes.
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
  Live and the old desk take it too. The commands are `page.make`, `page.lint`, `page.layout`, `page.list`,
  `page.organize` (rename, reorder, move, archive or restore pages in `_organize.json`, keeping the armed page where
  possible; the Desk's Organize sheet drives it without scrolling) and `page.open` (open a saved page by id);
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

- **The Song tab is the song in Live** (Anthony, 26 November 2026), read only: one lane per
  track of the open set (never the monitor's own), its Arrangement clips as regions with Live's names and colours
  (a muted clip or track is dimmed), under a bar ruler with the locators as named spans, Live's loop and its
  bars, and Live's playhead. Session clips are never read. It has no buttons. `arrangement.read` is the one read
  (`Desk.arrangement`: one short call into the pager, `m.DESK.arrangement()`): `{set, bars, beats_per_bar, tracks:
  [{id, name, color, muted, regions: [{id, start, end, name, color, muted}]}], locators: [{beat, name}]}`, starts
  and ends in beats. It is kept until the pager says a clip or a locator changed (`{"t": "arr"}`, from listeners
  on every track's arrangement clips and on the locators), and the page reads again then. A region is an element
  of its own with an id that holds while it stays where it is (`t3@16`: track 3, from beat 16), so regions can be
  edited later; nothing edits them now. `tests/app/test_song_live.py` checks the read and the page.
- The arranger (`contrib/arranger`, its own server on :8975) is a separate tool and is no part of the app any
  more: the Song adapter, its mount at `/app/song`, the `song.*` commands (`song.build` among them) and `set.open`
  were removed on 26 November 2026. Its render queue is still `zpkt.app.renderqueue` (below).

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
- **Modes.** A producer has one mode, `build`, and no menu: the agent advises, uses its three tools and reads files.
  It cannot edit a file or run a command, and nothing asks. For Claude Code that is `--permission-mode dontAsk`,
  `--allowedTools mcp__zpkt,Read,Glob,Grep`, `--disallowedTools Bash,Edit,Write,NotebookEdit,EnterPlanMode,ExitPlanMode`
  and `--strict-mcp-config` (never plan mode: there it described a page instead of making it). For Gemini it is
  Gemini's default mode, and the app answers its permission questions itself: yes to the three tools, no to the rest.
  The three tools run in every mode with no question. `/app/ask/?dev=1` shows a mode menu (remembered on the device;
  `?dev=0` hides it again) with "Ask first" (Gemini asks on the page before an edit or a command; Claude Code has
  nobody to ask there, so it is `build`), and under "Developer", "Edit files" and "Full (shell)". The table is in
  `ask/engines.py`.
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
- **Tools.** An agent has four tools and no others: make or change a page (`page.draft`), organize pages
  (`page.organize`: rename, reorder, archive or restore), read the state (`desk.state`, older name `state.read`,
  which also lists `units` with their ids and pads) and read the last measurement. When I want to try an alternative it makes
  a page with compare states, or changes the one it made (Pages, Compare), and links to it.
  They are app commands behind a small MCP server (`python -m zpkt.app.ask.mcp`) that calls
  `POST /app/ask/api/tool` with the session's token. The bus tags them `agent` and groups them by session. None
  moves Live, and an agent cannot name any other command.
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
