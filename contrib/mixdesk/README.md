# The HW002 mix desk

One screen for finishing HW002's mix in Live with an Arturia MiniLab 3. It shows every control that matters for the
mix, grouped into eight pages, with the MiniLab control each one sits on, and which page the MiniLab has armed. The
MiniLab has 8 knobs, 4 faders and 2 banks of 8 pads, far fewer than the mix needs, so a page arms a group of related
controls on it at once.

| Pad | Page | Faders | Knobs | Bank-B pads |
|---|---|---|---|---|
| A1 | Buses | kick, hats, break, chord buses | perc and transitions buses, sends to Space and Echo, headroom | bus and return mutes |
| A2 | Kick | kick, kick bus, saturator and glue wet | saturator drive/out, sub and knock EQ, glue | low cut, saturator, glue, KSMS match EQ, clip mode, solo |
| A3 | Hats | four hat lanes | three hat lanes, air, low cut, saturator, send | low cut, saturator, solo |
| A4 | Break | horn, stab, chop, beatbox | low cut, mid EQ, saturator, glue, send | low cut, saturator, glue, solo |
| A5 | Chord + perc | chord, splash, crash, chord bus | chord EQ and saturator, perc EQ, sends | cuts, saturator, solos |
| A6 | Transitions | risers, reverse, fills, downlifters | bus, EQ, sends | low cut, solo |
| A7 | Space | the two returns, hats and perc sends | Reverb decay, predelay, size, filter, shelf, width; Echo feedback, time | filters, solos |
| A8 | Main | glue wet and threshold, width, headroom | glue ratio/attack/release/out, mono-below, Main | bass mono, glue on, glue clip |

Four more pages are layers: press an armed page's pad again to flip to it (the page shows them as A1·2 and so on).

| Pad | Layer | What it holds |
|---|---|---|
| A1·2 | Match A/B | each bus's EQ on/off (B1-B6), bass mono, the transitions' low cut; each match move's gain on a knob |
| A2·2 | Kick EQ | sub bell, body cut and knock bands of the kick bus: gain, frequency, Q, on/off |
| A3·2 | Match highs | the air shelves on hats, perc, transitions and break: gain, frequency, on/off |
| A4·2 | Match lows+mids | the break's low shelf and mid cut, the transitions' low cut, Main's mono-below and width |

The big encoder steps through the pages too. `desk.json` holds the pages; edit it and press nothing else (the server
re-reads it when it restarts the pager).

- **Knobs** snap to the armed page's values (the MiniLab's knobs are realigned when a page is armed).
- **Faders pick up**: after a page change a fader does nothing until it passes the value Live has. The page draws a
  blue line where the fader is until then.
- **Pads B1-B8** flip the page's switches (device on, filter on, mute, solo).

## Matching the references (22 Nov 2026)

Anthony: "We have done spectral analysis of the reference. Match that your best." The match is EQ on the buses, fitted
with ears' calibrated `mlab target` and `mlab eqfit` (ears/mlab) and checked in Live:

1. `match.py render base` and `match.py stems` render the set and each bus solo (bars 1-40, ~16 s each in Live).
   The six solos sum to the mix within -117 dB, so EQ on a bus can be predicted exactly from its solo. `mlab eq-diff`
   on probe renders showed EQ Eight's bells and shelves within 0.25 dB of the RBJ curves the fit uses.
2. `mlab eqfit` fitted the controls in `fit.json` to the four HW002 references (build and drop windows). Four
   planning approaches were tried; the plan kept fixes each gap only on the bus that makes it, with no fader moves
   and the kick's sub boost capped at +6 dB as an A/B step.
3. `match.py apply` set it in Live; `mlab target` measured the render. Rms distance to the references' mean: drop
   2.58 -> 1.73 dB, build 4.73 -> 2.17 dB; outside their range: drop 0.83 -> 0.14, build 2.40 -> 0.29. Build-to-drop
   contrast 3.3 -> 4.2 LU (references 0.2-15.4); kick punch in the drop 7.0 -> 7.4 dB; true peak -4.2 -> -6.7 dBTP.
   Loudness and peak-to-loudness stay far from the references: those are the mastering step's.

The moves: kick sub +6.0 dB at 37 Hz (Q 1.34) and body -3.3 dB at 99 Hz; hats air shelf -6.5 dB from 4 kHz; perc
air -3.7 dB from 10 kHz; break low shelf -2.4 dB at 162 Hz, mid -4.0 dB at 715 Hz, air +1.8 dB from 5 kHz;
transitions high pass at 100 Hz (it takes the sub out of the sub drops, bar 25 included) and air -6.5 dB from 9 kHz;
Main's bass mono below 250 Hz. Every one is on a page, and each bus's EQ flips on A1·2.

`recipe.py write` puts the desk's state into the arrangement (`short-8d2a2.json`, key `desk`): returns, every desk
device's parameters, every mixer, each value as shown and raw. `recipe.py apply` sets it on a set; applied back onto
the finishing set its render nulls against the match render (-122 dB). The arranger keeps `desk` when it saves.

## Running it

1. `uv run --project hands python contrib/mixdesk/workspace.py save|clean|devices` made the set
   `HW002_121_pp_finish.als` (in the HW002 sets folder) from the arranger's mix set `HW002_121_pp_mix`: the
   canonical 8d2a2 arrangement, mix 1 and the kept kick, with an EQ Eight, Saturator and Glue Compressor on the buses,
   two returns (Space: Reverb, Echo: Echo) and a Glue and a Utility on Main. Every one starts where it changes nothing
   (EQ bands at 0 dB, Saturator and Glue at 0 % wet, sends down, bass mono off).
2. With that set in Live, `uv run --project hands python contrib/mixdesk/server.py` serves the page on
   127.0.0.1:8985 (`tailscale serve --bg --https=8985 http://127.0.0.1:8985` for the tailnet).

The server loads `pager.py` into Live's Python through hands' Remote Script. The pager grabs the MiniLab's controls
from Live's factory MiniLab_3 script (as `hands/remote_scripts/ZpktMiniLabTempo` does, at a higher priority, so the
tempo fader is the desk's fader 4 while the desk runs) and drives Live directly. Every change goes out as a UDP
datagram to the server, which streams it to the page. If a set load rebuilds the factory script, the server notices
within 5 s and starts the pager again.

Nothing in the page makes or plays sound: it shows and arms controls, and the mix is Live's (`contrib/docs/sound.md`).

## Listen and see (right half of the page)

The page is split: the control surface on the left, Live transport/monitoring and measurements on the right.

- `sources.json` names A (original), B (the recipe's reference match, rendered) and the references (C, four to pick from). Run
  `ears/.venv/bin/python contrib/mixdesk/analyze.py` (the ears venv) after you render a new A or B: it writes 16-bit WAVs and
  `analysis.json` (spectrum per 1/6 octave for build and drop, loudness/crest/width/bass-mono over time) to
  `~/_agent_scratch/mixdesk/viz/`. Nothing there changes a sound.
- Everything you hear comes from Live: `monitor.py ensure` places `mon A` and `mon B` (at beat 0) and `mon C1`–`mon C4` (at bar 17 /
  beat 64, warping off, muted by default) in the Arrangement. **Play**, **seek**, and **loop** drive Live's transport;
  switching **A** / **B** / **C** solos the chosen monitor track (bypassing Main's desk devices and matching loudness)
  and **W** goes back to the working mix itself, live, with your controls. Keys: A B W C, space, arrows, 1–4. The spectrum shows levels from the
  cached renders, each curve against the reference, or what the match moved against what the reference would move.

## History, undo and checkpoints

The bar under the page tabs keeps the mix's history (`history.py`):

- **Undo / Redo** (keys **Z** / **Shift+Z**): every move of a desk control is a step, whether it came from the MiniLab,
  this page or Live's own mouse. Moves of one control within 2 s are one step (a fader sweep), and a control moved back
  to where it started leaves no step. Moves the desk makes itself (a monitor switch bypassing Main's devices) are not
  steps. The history is kept in `~/_agent_scratch/mixdesk/history/<set>.json` and outlives a server restart.
- **Checkpoint** saves the whole mix (every fader, send, mute and device value of the set, about 3 s) as
  `<sets_dir>/state/<set>/<name>.json`, a hands state: `hands live state diff NAME` and `put NAME` work on it too, and
  every state there (B, `working-0854`, ...) is a checkpoint here. The server makes `start-<date>-<time>` when it starts,
  unless the desk made one in the last 12 hours.
- **Normal / Highlight / Only changed**: compare **from** a checkpoint **to** now or another checkpoint. Highlight lights
  the controls that differ (with what they were) and dims the rest; Only changed hides the rest and the pages with
  nothing changed. The page tabs count the changed controls.
- **revert** on a highlighted control, or **Revert these** for all of them, puts them back to the "from" checkpoint as
  one undoable step. **Whole mix** puts back everything the checkpoint holds, controls outside the desk too (`hands
  live state put`); a `before-revert-...` checkpoint of the mix as it was is saved first, because only the desk's
  controls can be undone.

## The page, and the live spectrum

Nothing scrolls: each side fits the window and is paged with buttons and keys.

- **Left, one MiniLab page at a time.** **Prev / Next**, the picker, or **[** / **]** arm the page on the controller
  too. Each control is a tile: its slot (K1, F1, B1), a dial or fader, the value as a large number with a small unit,
  and its name. Values ease to where Live puts them once a frame, however many messages arrive. **Show: All / Changes
  lit / Only changes** lights what differs from the checkpoint chosen under Changes; with Only changes, Prev/Next skip
  pages where nothing differs.
- **Right.** A / B / W / C, Play, the loop and the waveform stay on top (the reference picker shows only while C
  plays); **Spectrum / Over time / Numbers / Changes** are paged below with **‹ ›** or **,** / **.**. The history under
  Changes is paged too. The playheads are overlays, and a canvas is redrawn only when what it shows changes.
- **?** lists the keys and what the MiniLab's controls do. Under 900 px wide one side shows at a time (**Controls /
  Monitor**, or **Tab**).

The spectrum's blue curve is what Live plays now. `meter.py install` puts a Max for Live device, "zpkt desk meter",
last on Main (once; it passes the audio through untouched). It measures Main in 31 third-octave bands (Max's fffb~),
10 times a second, and sends the levels to the server on UDP 8987. The page averages them over about a second, eases
the curve every frame, and draws it on the renders' scale (both are the mid signal's power per band), so W can be
read against A, B and C as you turn knobs. With A, B or C monitored, the blue curve is that render as Live plays it.

## Make a surface

The last page on the left, **＋ Make a surface**: say what you want under your hands and press Make surface.
`surfaces.py` reads what the set holds (every track's mixer and devices, with what each parameter shows now and at
its ends: the pager's `inventory`), asks Claude for one page as JSON (the Claude Code CLI, headless, no tools), checks
every control against the set (what is not there is dropped and said so) and saves it as
`<sets_dir>/surfaces/<set>/<name>.json`, with the request. The pager is reloaded with it and its page armed. Every
file in that folder is a page of the desk after desk.json's own; **Remove** moves a file to `removed/`.

A control can be a **macro**: one knob or fader moving several parameters together, each from its "from" to its "to"
(written as Live shows them: "200 Hz", "-6 dB") as the control goes from 0 to 1. The history keeps the parameters a
macro moves, as one step, so undo puts each back exactly. `POST /api/surface/save {"surface": {...}}` saves a
ready-made surface through the same checks.

Claude must be signed in on this Mac for the CLI: `claude`, then `/login` (or a token in `HARNESS_OAUTH` / the
harness's Keychain item). When it is not, the page says so.

