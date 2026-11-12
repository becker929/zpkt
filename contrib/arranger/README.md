# The HW002 arranger

A phone page for trying arrangements of HW002 out of loops bounced from Live, and the pages after it. Each page
writes structure into the arrangement file, and the structure adds up to a recipe that the mastering step runs in
Ableton Live (Anthony, 12 November 2026: "All of this accumulates into a recipe for the mastering step to actually run
in ableton live").

| Step | Page | Writes | How it is heard |
|---|---|---|---|
| Arrange | `/` | `regions` | Loops bounced from Live, started together in the browser |
| Transitions | `/transitions/` | `transitions` (picks, levels, Live recipes) | Sounds made in Live, started over the loops |
| Mix 1: gain, pan, EQ cuts | `/mix/` | `mix` (per channel) | The same files through a gain, a pan and cuts in the browser |
| Mix 2: distortion, EQ boosts, compression, bus processing | not built yet | | Small batches rendered in Live: Anthony picks the ranges, a coarse grid of them is rendered, he plays the grid in the page |
| Master | not built yet | | Runs the whole recipe in Live |

Three ways to hear a change: offline DAW audio (renders), online browser audio (the first three steps, within the
named exceptions in `contrib/docs/sound.md`), and, for the second mix step, online small-batch DAW audio.

1. `uv run --project hands python contrib/arranger/bounce.py` solos each part of the set in Live and exports Main
   (15 bounces, about 6 minutes). Live must have the working copy `HW002_121_pp_loops` in front.
2. `uv run --project hands python contrib/arranger/mine.py` cuts those bounces into loops and one-shots on the bar,
   writes `loops.json`, and checks the song's own arrangement, summed, against Live's bounce of the mix.
3. `python3 contrib/arranger/server.py` serves the page on 127.0.0.1:8975; `tailscale serve` puts it on the tailnet.

The audio and the saved arrangements stay outside the repo (`~/_agent_scratch/arranger`).

The page starts the loops together on the bar clock and does nothing else to them (`contrib/docs/sound.md`: the
browser plays renders, it never makes sound). What it produces is a structure, not audio: each saved arrangement
names its loops by stem and source bar, so it can be rebuilt in the set and rendered in Live.

`shorts.py` writes the one-minute arrangements shown as tabs (the canonical 8d2a2), and
`uv run --project ears python contrib/arranger/measure.py short-8d2a2` prints a tab's level above 6 and 10 kHz for each
four bars, and its peak.

## Transitions

`/transitions/` plays the canonical arrangement (8d2a2) around one section change at a time (bar 9, the drop at 17,
25, the horn's return at 33, and the end going back to the top), looping, with any stack of transition sounds laid
over the change: risers, reverse reverbs, drum fills, bass scoops and downlifters, many more of each than a track
could use. What it produces is a structure: the stack at each change is written into the arrangement
(`arrangements/short-8d2a2.json`, `transitions`), each pick with the change it lands at, its beats, and the Live recipe
that made it (track, notes, automation, source hit), so the chosen transitions can be built into the set and rendered.
Each kind has a level fader at each change, a plain gain in the page (the one named exception in
`contrib/docs/sound.md`); its level goes into each pick as `gainDb` for Live to apply. Hearts, faders and the page's
view are kept in `~/_agent_scratch/arranger/transitions.json`.

Every sound is made in Live by `fxset.py`, in a copy of the set (its docstring has the recipe): Operator noise and
tones through Auto Filter for risers and downlifters, the set's own hits through Live's Reverb for reverse reverbs,
an EQ Eight on the kick group for scoops, and fills on the set's hat racks and kick and on Live's 909 Core Kit. Each
candidate sits in its own slot past the end of the song; one export per soloed track renders them all, and `cut`
slices the exports into `fx/audio/<id>.flac` and `fx/fx.json`. `contrib/docs/sound.md` says what the page may do.

