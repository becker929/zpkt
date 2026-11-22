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

The big encoder steps through the pages too. `desk.json` holds the pages; edit it and press nothing else (the server
re-reads it when it restarts the pager).

- **Knobs** snap to the armed page's values (the MiniLab's knobs are realigned when a page is armed).
- **Faders pick up**: after a page change a fader does nothing until it passes the value Live has. The page draws a
  blue line where the fader is until then.
- **Pads B1-B8** flip the page's switches (device on, filter on, mute, solo).

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
