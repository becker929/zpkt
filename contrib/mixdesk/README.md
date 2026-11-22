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
