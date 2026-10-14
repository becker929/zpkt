# The HW002 lab: the set's knobs as phone surfaces

> **Its sound is banned (14 October 2026).** The lab does the DAW's job in the browser, which zpkt no longer allows
> (`docs/sound.md`): its sketches of the set were plausible and wrong. Keep its surfaces (the knobs, pads, 3D
> pieces, haptics), not its sound; its sound is replaced by the player engine. The design that follows the lab is
> `docs/studio-agent.md`. The rest of this page describes the lab as it was built.

A test bench for playing with HW002 on a phone. It takes the set's 100 most salient parameters and lays them out as
control surfaces, organised by the steps of the workflow (`docs/workflow.md`) it is about: collage, arrange, kick
and mix, plus a fifth tab of stranger instruments. HW002's own stems play under every control, so each move is
heard at once.

It runs inside `harness serve`, behind the harness password, at `/studio/lab/` (studio's menu has a row for it).
Nothing it does reaches Live: it is a sketch of the set on the phone, made to find what to try in Live next. "Copy
changes" in its menu gives every moved knob in Live's terms, ready to become a plan (`hands plan`).

## What it plays, and how a control sounds

- **The stems**: the canonical Short's 36 s version (bars 121-144 of the song), as the kick group (kick and rumble),
  perc group and SFX group, on a 160 BPM bar clock. The canonical Short itself (batch 4.3 track 1, 30 s) is there
  too, for its real A, AB, ABC and ABCD hat bars.
- **The whole song**, for the arrangement map.
- **The collage's sources**: every file the set's clips play (ARC Raiders, the splash, the chord loop, the two 2023
  synth stems, the 2023-10-07 recording, the beatbox, the rumble bounce), each cut to the part the set plays with
  10 s either side (at most 60 s), so a phone keeps them all in memory.
- **Kick hits** cut from the kick stem, on the beat.

The stems already carry the set's sound, so every control is silent at the set's value and plays only the change:
+6 dB on the kick bus's 30 Hz shelf is a 30 Hz shelf of +6 dB on the kick group's stem. What cannot be taken back
out of a stem (less drive than the set has, a layer inside the kick group) is approximated or not heard; the
surfaces' own instruments (the kick synth, the collage's players) make their sound from scratch and follow the full
values. `js/audio/sketches.js` says how each kick and mix param is sounded.

## The 100 parameters

`harness lab-params` writes `static/lab/data/params.json` from the list in `harness/studio/lab_params.py`, reading
each value from the set (`~/_agent_scratch/HW002/HW002_121_full.als`; COLDFIRE shows a knob only once its window has
been opened, so two come from the probe kits). Chosen from what the experiments touched (batches 4-8, the batch 6
climbs, the references' gaps) and what each step is about:

| Stage | n | Groups |
|---|---|---|
| kick | 34 | the scoop, distortion (COLDFIRE, Decapitator, Roar), the drum rack's layers, the transient shaper, the kick bus EQ, its compressor, the rumble |
| mix | 22 | group levels, hat layer B, mono low end, space (perc 2 Supermassive), colour, drop power (the Main's glue rack), the SFX bus |
| arrange | 22 | length, the scooped opening, the kick's entry, the hat staircase, splashes, breaks, the chord loop, the SFX's entry |
| collage | 22 | the game audio's chain, the chord loop's colour and texture, the break synths' filter and drive, the recordings, the break bus |

Each carries its knob in Live as hands names it (`track|Tag:index|param`), its value in the set, the range an
experiment tried and what it found; a long press on any control shows them. Arrangement choices have no knob: their
"set" value is the canonical Short. A surface's own controls (a synth's pitch drop, a grain size) are in
`data/extras-<stage>.json` and are not among the 100.

## The surfaces

Every control shows the set's value in acid green and the tried range as a pale band. Drags are relative; two
fingers, or a press held still before moving, are fine. Double tap: back to the set. Long press: the inspector. The
transport has snapshots A-D (tap an empty one to save, tap a full one to recall, hold to save over), undo, and the
set's own mix to compare against.

- **Collage (I)**: a shelf of the sources as cassettes; a granular scrub (each finger a voice; freeze, a wandering
  ghost, tilt); a slicer on 4x4 pads with a 16-step pattern; tape stop, bend and varispeed on the whole collage;
  resampling the next 1-8 bars into a new cassette; a bed of six lanes over the stems' 24 bars, with the set's own
  collage and its break as presets; every source's chain and the break bus as racks; a "found sound" dice.
- **Arrange (III)**: the Short on a timeline you drag (length on the 33-50 s zone, the scooped opening, the kick's
  entry, breaks, splashes, the SFX's entry), with the loudness of each bar against the set's Short and the
  references' two breaks; the hat staircase with Anthony's rule; play the Short once with a count-in; three versions
  switching every 2 bars; the whole song's map (tap a bar to hear the song from there); the bar library. The hats are
  the canonical Short's own bars; masks fill in layer sets it has no bar of. `harness lab-bars` rebuilds the bar
  analysis (`data/arrange-bars.json`).
- **Kick (IV)**: a kick synth built in the set's device order (the drum rack's 052 body with its COLDFIRE and
  transient shaper, the 060 knock, the offbeat pad, FlexVerb; the rumble through a dark room, the Decapitator, its EQ,
  a duck under each kick and bass mono; the kick group's EQ, Roar, COLDFIRE, compressor and two 48 dB/oct scoops),
  calibrated against the kick stem and following all 34 kick params at their full values. A source switch (the stem,
  the synth, both, or the two a bar each, loudness-matched), with one of HW002's own hits as a layer. In thumb reach:
  HEAT, one fader for COLDFIRE and the Decapitator together with batch 8.1's 37-50 % drawn, and A/B/C at 37, 43.5 and
  50 % taking turns every bar or two, matched in loudness; a giant hold-to-scoop pad over a live spectrum (slide to
  move it; a "sub cut" zone below 70 Hz) and a 4-bar latch. Then one hit drawn over the set's own (wave, spectrum,
  the 31.6 Hz band and crest against the references), pitch and level envelopes you draw, the layers as pads, the
  Decapitator's five styles on a chicken-head rotary, the kick bus EQ as a curve with the colour climb's path, the
  transient shaper's zones, the compressor's transfer curve (idle at the set, as measured), and the rumble with a
  hold-to-hear-it-alone pad and a low-end correlation meter.
- **Mix (V)**: a desk (the three groups and two returns: faders, LED meters, mute and solo, sends); a BS.1770
  loudness meter on the audio thread (momentary, short-term, integrated, true peak, PLR, block crest, low-end
  correlation) with the target and the references; a level-matched A/B against the set's render, every bar or two;
  the six aspects of the batch 5/6 climbs as a radar (each axis from the set to the climb's best); a third-octave
  analyser with the references' gaps (deep sub, mids, air) and EQ curves you drag; a goniometer with the low end's
  correlation; drop power (the glue rack, a clipper, the batch 5 preset); space as a hall you stretch.
- **Play**: machines that move the params: a raymarched furnace and a demoscene tunnel in WebGL you play with a
  finger, a 3D die whose faces are the snapshots, the six gaps as a crystal, tilt, balls thrown by the kick, a Lorenz
  attractor, a gesture looper, nested gyro rings, a 16-step lane, an A/B flipper. At the bottom, the Bench: a Max-style
  patcher of the widget library (dials, multisliders, nodes, matrixctrl, xy pads, meters) with tempo-locked
  modulators (cycle~, phasor~, noise, step, env) you patch into any param with cords. Machines and modulators move a
  param through the store's modulation, on top of its knob; Keep writes what you hear into the knobs.

## Running it

```bash
cd lib/harness
uv run harness lab-audio      # the stems, sources and kick hits, to HARNESS_LAB_AUDIO (~/_agent_scratch/lab/audio)
uv run harness lab-params     # the 100 parameters, read from the set (static/lab/data/params.json)
uv run harness lab-bars       # the arranger's bar analysis (static/lab/data/arrange-bars.json)
uv run --extra dev python tests/ui/lab_server.py --port 8799   # the lab alone, no login, for development
```

The audio never goes in the repo (Anthony's set, his stems and samples); the lab's files are relative ES modules
with no build step (`static/lab/`, served by `routes.lab_file`). Tests: `tests/test_studio_lab.py` (the parameter
list, reading a set, the routes) and `tests/ui/test_lab.py` (on a stand-in audio folder: it starts, every surface
mounts with no errors, a knob drag moves its param, every sketch is silent at the set, a channel strip at rest is
flat).

## Limits

- It is a sketch: Web Audio stands in for COLDFIRE, the Decapitator, Supermassive and the rest, and the stems carry
  the set's processing, so less than the set's drive or reverb cannot be heard. Live decides.
- Haptics, tilt and the motion permission are written for iPhone Safari and were tested only in WebKit on the Mac.
- Resampled cassettes live in memory until the page reloads.
