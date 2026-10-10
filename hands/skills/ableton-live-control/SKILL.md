---
name: ableton-live-control
description: Drive Ableton Live 12 (release build, not beta) agentically — read and write tempo, transport, tracks, clips, MIDI notes, devices/parameters, scenes, routing, and the full Live Object Model, plus property listeners — with no GUI clicking for data-model control. Primary path is OSC (AbletonOSC); an optional advanced path runs arbitrary LOM Python via an MCP TCP bridge. Use when asked to control, script, automate, inspect, or build a Live set, or to run a closed loop that edits a set and verifies the result. Includes off-screen operation via a virtual display and first-time setup of the AbletonOSC remote script.
---

# Agentic control of Ableton Live 12 (release)

This skill gives an agent exhaustive, non-GUI control of **Ableton Live 12
release** (verified against 12.4.5 Suite) through **AbletonOSC**, an MIT-licensed
MIDI Remote Script that exposes the Live Object Model (LOM) over OSC. No beta, no
Extensions SDK, no Accessibility clicking for the data model.

- Live listens on **UDP 11000**; replies come back on **UDP 11001**.
- Everything is driven by `scripts/live.py` (a dependency-free OSC client +
  Python library). Full address list: `reference/osc-api.md`.

## Quickstart (copy-paste)

**Run this first, always** — `doctor.sh` is a one-shot, non-destructive preflight
that tells you your exact starting state (Live up? OSC up? MCP up? window
on-screen? modal blocking?):

```sh
bash scripts/doctor.sh            # exits 0 if at least one control path is up
```

If a path is down, do the one-time enable:

```sh
bash scripts/install_abletonosc.sh                 # only if AbletonOSC not on disk
# open Live -> Settings... -> Link/Tempo/MIDI, then:
bash scripts/enable_osc.sh 2                        # select AbletonOSC into free row 2
```

Verify each path, then send a first command:

```sh
bash scripts/osc_up.sh                              # Path A health check
bash scripts/mcp_up.sh                              # Path B health check (optional)
python3 scripts/live.py /live/song/get/tempo        # first real command
```

See "Setup" below for the full one-time enable walkthrough and safety notes.

## Two control paths

| | **Path A — AbletonOSC** (primary, verified) | **Path B — LOM `execute()`** (advanced) |
|---|---|---|
| Tool | `scripts/live.py` | `uv run hands live exec` (zpkt `hands/`) |
| Transport | OSC, UDP 11000/11001 | JSON-over-TCP, port 16619 |
| Surface | fixed OSC vocabulary (see `reference/osc-api.md`) | arbitrary Python against the full LiveAPI |
| Setup | install AbletonOSC (below) | requires the AbletonLiveMCP Remote Script selected as a control surface; the client is the `hands` package |
| Safety | robust, hard to crash Live | powerful but **crash-prone** — follow `reference/lom-guide.md` |

> **Cursor takeover rule (enforced, not remembered):** any step that moves the
> physical pointer is a takeover of the user's cursor, which MUST end back at the
> center of their primary physical display. This is enforced in the scripts, so
> you do not rely on remembering it:
> - `enable_osc.sh` and `hands live export` self-park on every exit path
>   (success or error) -- no extra step needed.
> - Any **ad-hoc** pointer command (e.g. the manual dropdown-selection fallback,
>   a one-off clicking `osascript`) must be run through the wrapper, which parks
>   on every exit path and preserves the exit code:
>   ```sh
>   bash ~/.agents/skills/virtual-display/scripts/with-cursor-parked.sh cliclick c:1200,680 c:1185,711
>   ```
>   Never run a raw `cliclick` directly. Pure OSC/MCP control never touches the
>   cursor and needs no parking.

**Default to Path A.** It is self-contained, verified against Live 12.4.5, and
sufficient for almost everything (transport, tracks, clips, notes, devices,
parameters, scenes, routing, listeners, closed-loop readback). Reach for Path B
only when you need something outside AbletonOSC's vocabulary (browser navigation,
device insertion, automation envelopes, drum-rack internals, audio recording via
a resampling track). Path B is only available when the MCP bridge is up
(`nc -z 127.0.0.1 16619`); otherwise `hands live exec` exits 1 with "Cannot reach Ableton".

The only thing **neither** path does directly is a post-FX **audio bounce to a
file** via Live's native dialog — see "Audio export" at the bottom.

### Which path? (decision tree)

- **Transport, tracks, clips, MIDI notes, existing device parameters, scenes,
  routing, listeners** -> **Path A** (`live.py`). Always try this first.
- **Browser navigation, device insertion, automation envelopes, drum-rack
  internals, arrangement editing, audio recording via a resampling track**
  -> **Path B** (`hands live exec`), but only if the bridge is up
  (`nc -z 127.0.0.1 16619`). If the port is closed, Path B is unavailable —
  fall back to Path A or the one-time surface enable.

## The 30-second check

Before anything else, run the preflight (see Quickstart) or the quick health
checks:

```sh
bash scripts/doctor.sh        # full preflight: Live/OSC/MCP/cliclick/window/modal
bash scripts/osc_up.sh        # Path A only: prints "AbletonOSC is up ...", exit 0
bash scripts/mcp_up.sh        # Path B only: round-trips 1+1 over TCP 16619
```

If a path is up, skip setup and go straight to "Controlling Live". If not, do
"Setup".

## Controlling Live

Send any OSC address with `live.py`. Bare numeric args auto-type; prefix `s:`
forces a string, `i:` int, `f:` float.

```sh
python3 scripts/live.py /live/test                       # -> ok
python3 scripts/live.py /live/song/get/tempo             # -> 160.0
python3 scripts/live.py /live/song/set/tempo 128         # (no reply; fire-and-forget)
python3 scripts/live.py /live/song/start_playing
python3 scripts/live.py /live/track/set/volume 0 0.7
python3 scripts/live.py --json /live/song/get/track_names
```

Batch many messages (one per line, faster than re-invoking):

```sh
printf '%s\n' '/live/song/set/tempo 124' '/live/track/set/mute 0 1' | python3 scripts/live.py --batch
```

Stream a property listener until Ctrl-C. Subscriptions use the `start_listen`
address (updates then arrive on the matching `get` address):

```sh
python3 scripts/live.py --listen /live/song/start_listen/beat
```

As a library for closed loops:

```python
import sys; sys.path.insert(0, "scripts")
from live import Live, LiveError
live = Live()
if live.ping():
    live.set("/live/song/set/tempo", 140)
    print(live.get("/live/song/get/tempo"))     # [140.0]
    live.call("/live/clip_slot/create_clip", 2, 0, 4)   # MIDI track only
    live.call("/live/clip/add/notes", 2, 0, 60, 0, 1, 100, 0)
    print(live.get("/live/clip/get/notes", 2, 0))
```

### Behavior you must know (see reference/osc-api.md for the full table)

- **Only `get/*` addresses reply.** `set/*` and method calls (e.g.
  `start_playing`, `create_midi_track`, `create_clip`, `add/notes`) send **no**
  reply — verify their effect with a follow-up `get`. `live.py` auto-waits only
  when the address contains `/get/` (override with `--wait` / `--no-wait`).
- **Index echo:** `track`/`clip`/`clip_slot`/`device`/`scene` `get` replies
  prepend the index arg(s) you passed. `song`/`application`/`view` do not.
- `create_clip` works on **MIDI tracks only**; it fails silently on audio tracks.
- `version` returns only `major minor` (e.g. `12 4`), no patch component.
- `track_data` bulk reads need `obj.prop` names (`track.name`, `clip.name`,
  `device.name`); use `-1` for "all tracks".
- A handler that gets bad args raises and sends nothing, so the request just
  times out. Fix the args instead of retrying.

### Verify it worked (get-after-set)

Because `set/*` and method calls send no reply, always **read the value back**
with a `get` to confirm the change actually landed:

```sh
python3 scripts/live.py /live/song/set/tempo 128
python3 scripts/live.py /live/song/get/tempo        # -> 128.0 confirms it stuck
```

The same principle applies on Path B, but there you must read in a *separate*
call (post-set readback in the same call crashes Live — crash Rule 1).

## Path B: arbitrary LOM Python via `hands live exec` (advanced)

When the MCP bridge is running, execute Python directly against Live's object
model. Inside the executed code these globals exist (provided by the Remote
Script): `song, app, tracks, returns, master, browser, Live,
MidiNoteSpecification, find_item, find_items, find_track, load_to, log, json,
time`. Expressions are eval'd and returned; for statement blocks, assign to
`result`.

**Top 3 crash rules (memorize these; full list in `reference/lom-guide.md`):**

1. **No post-set readback** — never read a property in the same call that wrote
   it (`param.value = 0.5; result = param.value` crashes Live). Write in one
   call, read in the next.
2. **<=20 params per call** — limit to one device and its first ~20 parameters;
   iterating all params of all devices exhausts LiveAPI memory.
3. **Sleep between browser loads** — put `time.sleep(0.3)` between consecutive
   `load_to()` / `browser.load_item()` calls to avoid silent race conditions.

Run these in zpkt's `hands/` (or add `--project <zpkt>/hands` to `uv run`):

```sh
uv run hands live ping                                       # is the Remote Script listening?
uv run hands live exec "song.tempo"                          # eval expression
uv run hands live exec "song.tempo = 140"                    # exec statement
uv run hands live exec "result = [t.name for t in song.tracks]"
uv run hands live exec --json "result = len(song.tracks)"
uv run hands live exec --file snippet.py                     # or --stdin
```

`--retries N` (default 2) retries only while connecting, when the request cannot
have reached Live. A request that was sent is never resent: it may still run,
and running it twice could double a mutation.

```python
from hands.live.transport import LiveClient, LiveError
live = LiveClient()
print(live.run("song.tracks[0].name"))   # raises LiveError on any failure
```

**Before writing nontrivial `execute()` code, read `reference/lom-guide.md`** —
the LiveAPI crashes easily (no post-set readback, no large parameter sweeps,
sleep between browser loads, etc.). That guide mirrors the canonical
`ableton-guide` skill in `hands/.cursor/skills/`. The `hands` package
(`hands.live`: sessions, time edits, knobs, export) is the productionized
consumer of this path and the best reference for real recipes.

## Setup (only if `osc_up.sh` failed)

### 1. Install AbletonOSC (one-time, persists on disk)

```sh
bash scripts/install_abletonosc.sh          # --force to reinstall
```

### 2. Get Live running (off-screen recommended)

To keep Live off the user's physical screen, use the sibling **virtual-display**
skill (`~/.agents/skills/virtual-display`):

```sh
bash ~/.agents/skills/virtual-display/scripts/create.sh          # note the origin, e.g. (1440,0)
bash ~/.agents/skills/virtual-display/scripts/run-on-vdisplay.sh "Live" 1600 120
```

If Live is already running on the user's main display, that's fine too — OSC works
regardless of where the window is.

### 3. Enable the AbletonOSC control surface (one-time, then persists)

This is the **only** step requiring GUI automation, because Live's Control
Surface chooser is a custom-drawn list, not a native menu. Once selected, the
choice is saved in Live's Preferences and survives restarts.

1. Open Live's Settings on the **Link/Tempo/MIDI** page (Live menu -> Settings...;
   note: three literal periods, and do NOT use Cmd+, — on the virtual display that
   has triggered a "Save As" dialog instead).
2. Run the helper (defaults to Control Surface **row 2**):

   ```sh
   bash scripts/enable_osc.sh 2
   ```

3. **Verify with one screenshot** that the intended row now shows "AbletonOSC"
   (use `bash scripts/snap.sh /tmp/cs.png 1050x380+1220+680`, then read the crop).

**CRITICAL SAFETY:** Row 1 is often the user's real hardware controller (on this
machine it is a MiniLab 3). **Never select AbletonOSC into a row that already has
a controller.** Use a free row (one that reads "None"); default is row 2. Live's
Settings table is NOT reliably introspectable via the accessibility API (all rows
report the same value), so confirm free rows visually, not via the AX tree.

If `enable_osc.sh` reports it didn't come up, the pixel offsets are off for the
current UI scale — take a cropped screenshot of the Control Surfaces table
(`bash scripts/snap.sh`) and select `AbletonOSC` in the free row's dropdown
manually with `cliclick` (open the dropdown, click the `AbletonOSC` item, which
sits 2nd in the list after "None").

Confirm success:

```sh
bash scripts/osc_up.sh
```

(`enable_osc.sh` drove the pointer with `cliclick`, but it self-parks the cursor
on exit, so the cursor is already back on your primary display.)

The Live log (`~/Library/Preferences/Ableton/Live <ver>/Log.txt`) will show
`Started AbletonOSC on address ('0.0.0.0', 11000)` when it's active.

> **Future improvement (not yet implemented):** the AbletonOSC / AbletonLiveMCP
> control-surface selection persists in Live's Preferences file. It could be
> pre-seeded offline (edit the Preferences before launch) to remove this last
> GUI step entirely, making enablement fully headless.

## Working off-screen without burning context (READ THIS)

Screenshots of the Retina virtual display are ~15 MB at 5120x2880. Reading many
full-resolution PNGs into context is what previously ballooned a session past 1M
tokens. When you must look:

- **Prefer OSC/text over screenshots.** Almost all Live state is available via
  `get/*` — use it. Only screenshot for GUI-only steps (enabling the control
  surface, audio export).
- **Always use `scripts/snap.sh`, never raw `screencapture`.** `snap.sh` is the
  only sanctioned screenshot path: it always crops/downscales and enforces a KB
  budget (default 700 KB), so a raw ~15 MB Retina PNG can never reach context.
  It replaces ad-hoc `screencapture` + `magick`.

  ```sh
  bash scripts/snap.sh                                # whole screen, downscaled
  bash scripts/snap.sh /tmp/cs.png 1050x380+1220+680  # crop the Control Surfaces table
  ```

  Signature: `snap.sh [OUT_PNG] [CROP_WxH+X+Y] [MAX_WIDTH]` (defaults
  `/tmp/vd_snap.png`, no crop, width 1000; env `BUDGET_KB`, `DISPLAY_ID`).
- **Overwrite one scratch path** and only read it when you actually need to eyeball
  state; don't accumulate a gallery of old shots. `snap.sh` writes one scratch
  path by default.
- Coordinate mapping for cliclick (global logical points) vs a full capture pixel
  `(px,py)`: `global = (px/2 + origin_x, py/2)` where `origin_x` is the virtual
  display's origin (≈1440 here). Inverse: `px = 2*(gx - origin_x)`, `py = 2*gy`.
  Verify the origin from `create.sh` output rather than assuming.

## Troubleshooting / wedge recovery

Run `bash scripts/doctor.sh` first — it now surfaces most of these automatically
(OSC/MCP reachability, cliclick, the front window's position, and whether a
blocking modal is present).

| Symptom | Likely cause | Fix |
|---|---|---|
| `osc_up.sh` fails but Live is running | Control surface not selected, lost on restart, or firewall blocking loopback UDP | Do Setup step 3 (`enable_osc.sh`), re-check the free row, allow loopback UDP |
| `mcp_up.sh` port open but no answer | AbletonLiveMCP surface wedged | Try one simple call, or re-select the surface |
| An unexpected dialog/menu appeared | GUI automation triggered a modal (launch nag, "save changes?", overwrite prompt, plugin window) | `bash scripts/dismiss_modals.sh` (check), then `--reap` to auto-dismiss safe modals; if it aborts (exit 3), inspect `/tmp/modal_abort.png` |
| Live window jumped onto the user's physical screen | GUI automation (activate, Cmd+Shift+R, native Save panels) pulls the window/dialog to the main display | Move it back off-screen: `osascript -e 'tell application "System Events" to tell process "Live" to set position of window "Untitled" to {1600, 120}'` (X >= the virtual-display origin), then `bash scripts/osc_up.sh` |
| Port 11001 busy | Only one process can listen on the reply port at a time | `live.py` sets SO_REUSEADDR/REUSEPORT; still, run OSC commands sequentially, not in parallel |
| A track has real clips but captures as pure digital silence, under every method | Likely not a capture bug — check whether it's a MIDI track with no instrument device in its chain | See `reference/lom-guide.md` section 8 ("Diagnosing Silent Tracks"): check `has_midi_input`/`device.type`, then diff `.als` backups to see if an instrument was removed |

**`dismiss_modals.sh` behavior:** default check mode only *reports* modals and
their buttons (touches nothing). `--reap` dismisses ONLY recognized,
non-destructive modals via their safe button (Cancel > Don't Save > No > Close >
OK), or Escape for native Save/Open/Export panels; it NEVER presses a
destructive button (Save/Replace/Overwrite/Yes/Delete). On anything unrecognized
or destructive-only it aborts loudly, printing the title and writing a cropped
`/tmp/modal_abort.png`. Exit codes: `0` clean, `2` modal present (check mode),
`3` abort/inspect, `4` Live not running.

**Manual modal escape (last resort):** if `dismiss_modals.sh` can't help, send
Escape and repeat while extra windows remain:
`osascript -e 'tell application "System Events" to key code 53'`.

## Audio export / rendering to a file

The Live Python API has **no** render/bounce function, so getting audio onto disk
needs one of these:

1. **Native Export dialog (the default: offline, about 10x faster than real time).**
   `hands live export OUT [--start BEAT --length BEATS] [--mode Main] [--bits 32]`
   in zpkt `hands/` selects the range and runs `export_audio.applescript`
   (`hands/src/hands/live/`), which drives File -> Export Audio/Video
   (Cmd+Shift+R) + the native Save panel, then parks the pointer. From Python:
   `hands.live.render.export(client, out, start_beat, length_beats)`, then
   `hands.audio.check_audio(out, seconds=...)` to catch a silent render.
   The script takes `<absOutPath> [WAV|AIFF|FLAC] [16|24|32] [sampleRate] [lengthBars] [trackMode] [startBar]`.
   It contains a ground-truth element map for Live 12.4.5 (every dialog
   control, including the "Rendered Track" chooser, is DIRECTLY AX-addressable
   -- no cliclick pixel-guessing except the Save panel's unnamed filename
   field). `trackMode` selects what gets rendered: `"Main"` (default, the full
   mix), an exact track name (isolates that one track -- Live still appends
   " <TrackName>" to the filename, which the script resolves and returns), or
   `"All Individual Tracks"` / `"Selected Tracks Only"` (one file per track in
   a single pass, using the requested filename as a shared prefix). It resolves
   `cliclick` automatically (PATH first, then the Apple-Silicon `/opt/homebrew`
   and Intel `/usr/local` Homebrew prefixes), raises the Export dialog via
   AXRaise before every click/press so a dialog left behind by a prior run
   (which can end up BEHIND the main Live window) is never missed, and presses
   Export/Save/Replace via AXPress (not pixel clicks) so z-order can't cause a
   silent miss. GUI automation still tends to pull Live's window and the Save
   panel onto the user's physical display if Live isn't already parked on a
   virtual one -- run it there and be ready for wedge recovery (above).
   **Gotcha:** the dialog's Render Start defaults to wherever the arrangement's
   edit cursor last sat, not bar 0 -- pass `startBar` explicitly (default 0)
   or a bounce can silently render an unintended, possibly-empty region.
   This path moves the physical pointer, but `hands live export` parks the cursor
   on the primary display when it finishes (success or error), so no extra step.

2. **LOM resampling capture (real time, no GUI).** Route/arm a resampling track
   and record the arrangement for N beats over Path B
   (`hands record --arrangement --beats 64 --output render.wav`,
   `hands.live.record`). It runs at 1.56x real time; use it only for what
   export cannot do.

For agent-verifiable results **without** any file bounce, prefer reading state
back over OSC (notes, parameters, meter levels, playing status) to close the loop.

## Files

| Path | Purpose |
|---|---|
| `scripts/doctor.sh` | **Run first.** One-shot non-destructive preflight: Live/OSC/MCP/cliclick/window/modal. Exit 0 if any control path is up |
| `scripts/live.py` | OSC client + Python library (the main tool, Path A) |
| `scripts/osc_up.sh` | Path A health check: is Live reachable over OSC? |
| `scripts/mcp_up.sh` | Path B health check: round-trips `1+1 -> 2` over TCP 16619 (twin of `osc_up.sh`) |
| `scripts/install_abletonosc.sh` | Download/install AbletonOSC into the User Library |
| `scripts/enable_osc.sh` | Select AbletonOSC as a Control Surface (GUI, one-time) |
| `hands live exec` / `hands live ping` | Path B client (zpkt `hands/`): arbitrary LOM Python over TCP 16619 |
| `scripts/dismiss_modals.sh` | Modal reaper: check for modal dialogs; `--reap` safely dismisses non-destructive ones, aborts (exit 3) on anything unrecognized/destructive |
| `hands live modals [--reap]` | what `dismiss_modals.sh` runs (zpkt `hands/`; its AppleScript is `src/hands/live/reap_modals.applescript`) |
| `scripts/snap.sh` | The only sanctioned screenshot path: always crops/downscales and enforces a KB budget |
| `reference/osc-api.md` | Exhaustive OSC address reference + quirks (Path A) |
| `reference/lom-guide.md` | LOM crash-avoidance rules + idioms for Path B (mirror of the `autodaw/hands` `ableton-guide` skill) |
| `hands live export` | Native audio export (GUI, verified; zpkt `hands/`): Main / isolated-track / all-tracks-at-once modes |
