# An industrial techno short (stopped at v8)

A hard industrial techno short (41.6 s, 150 BPM, A phrygian), made in Ableton Live 12 Suite by hands from scratch and
checked by measurement. Anthony asked for it on 15 October 2026: "a techno banger short from scratch using the vec 2
clubby kicks, 808s, acid bass riffs and stabs. Use the plugins from hw 002. Go for hard industrial."

Stopped after v8 on Anthony's verdict (below). This folder keeps what is needed to learn from it: the recipe that
rebuilds every version, the v8 set's full device state (`set-v8.json`), COLDFIRE's knob maps, and the measurements.
The Live set itself is not in git (it carries HW002's own chains and the samples are purchased).

## Verdicts (Anthony's words)

- **v7:** "needs to be a lot harsher. Probably needs a lot more mids coming from the kick. Probably needs layers to do
  this, as well as more intense distortion. You'll want to use COLDFIRE ... More wet in the synths is a good idea.
  We may need to enhance ears so you can pick up on the differences."
- **v8:** "This sounds very flat and smooshed. Barely any dynamics or space. The kick sounds worse after the last
  feedback."

## What was made

- **Sounds.** VEC2's clubby kicks (060 as the body, on its A at 55 Hz, which sets the key; 117 as the top), a VEC2
  acid one-shot (Acid Sounds 009, A2) played as a 303 line in a mono, gliding Simpler whose resonant MS2 filter
  follows velocity (accents open it), a VEC2 A-minor stab (Synths 009) played one note per hit, a VEC2 reversed
  cymbal into the drop, and Live's 808 Core Kit (rim, clap, toms, cowbell, a long boom). VEC2 has no 808s.
  v8 adds two VEC2 hard kicks as layers (067 for 1-2.5 kHz bite, 037 for 2.5-6 kHz edge).
- **HW002's plugins, as HW002 set them.** `strip.py` copies HW002's set and keeps only its device chains (every clip,
  envelope and locator goes). Each new MIDI track feeds an HW002 audio track's chain (that track's input is the new
  track, monitored; the new track sends only): the rumble (kick into a 100 % wet 4 s reverb) through HW002's rumble
  chain (Shifter, Decapitator, EQ, LFOTool's duck) inside the kick group (Roar, COLDFIRE, EQ, Compressor); the stabs
  through the chord chain (LFOTool, Supermassive, COLDFIRE) and the SFX bus's Hybrid Reverb; the 808 through the
  beatbox chain (COLDFIRE, Supermassive, Compressor). The acid has its own Decapitator, EQ and Supermassive. Main:
  Utility (bass mono < 120 Hz), Glue Compressor, StandardCLIP (off), Limiter (true peak, -1 dB, +9 dB in).
- **Form** (`parts.py`): intro 4 bars (opens on the kick), build 8, break 4 (no kick, long stabs, falling 808 toms,
  the riser), drop 8 (stabs every 3 sixteenths, the acid jumping octaves, clap on 2 and 4), a last hit and its tail.
  Technique numbers came from a research pass over production guides (rumble chain, 303 rules, hat velocities
  55/40/110/45, -6 to -7 LUFS at the drop).

## Versions

| | what changed | measured |
|---|---|---|
| v0 | first build, no master chain | -11.9 LUFS; drop sub -12.8 dB of the mix (refs -3 to -8), low-mid -6 (refs -8 to -18) |
| v1-v2 | master chain; kick-group EQ retuned from HW002's kick (+11 dB at 330 Hz) to 55 Hz | -13 LUFS: HW002's Main fader sat at -6 dB |
| v3 | Main fader 0 dB | -7.1 LUFS, -0.9 dBTP |
| v4-v6 | toward the references' band balance: acid -7, 808 chain -4 (the most mid energy), rumble +6.5, hats -2.5 | drop: low, low-mid, presence inside the refs; mids 3 dB over |
| v7 | a bar of tail, 1.5 s fade | -7.3 LUFS, LRA 1.9; sent |
| v8 | harsh kick layers on HW002's driven COLDFIRE pads (+5 dB, Color 0.75, a 325 Hz low-pass removed); wetter stabs and acid | kick shape inside the refs on every band; drop mids 5 dB over the refs; LRA 2.4 |

Kick shape, bands in dB against the kick's own body (63-160 Hz), from `listen.py kickshape` (our kick-and-rumble stem
against the references' kick-alone bars):

| | box | mid | bite | edge | fizz |
|---|---|---|---|---|---|
| v7 (kick alone) | -4.7 | -13.9 | -16.3 | -23.2 | -27.1 |
| v8 | -7.2 | -7.9 | -7.2 | -16.8 | -22.6 |
| references | -5 to -18 | -8 to -17 | -10 to -14 | -13 to -17 | -18 to -25 |

Dynamics and width, whole files (ours 41.6 s, the references whole tracks, so LRA compares only roughly):

| | LUFS | PLR | LRA | crest | 100 ms level p95-p10 | side/mid |
|---|---|---|---|---|---|---|
| v7 | -7.3 | 6.3 | 1.9 | 9.1 | 11.0 | -7.1 |
| v8 | -7.0 | 6.1 | 2.4 | 8.8 | 10.7 | -7.7 |
| references | -4.3 to -7.2 | 4.2 to 6.8 | 5.6 to 16.4 | 6.0 to 8.2 | 11.0 to 22.1 | -11.0 to -18.0 |

## What to learn from it

- **The targets were spectra, and the verdict was about dynamics and space.** Every round matched band balance (mix
  and kick) to the references; nothing measured section contrast, depth or wet/dry contrast. v8 is inside the refs'
  spectra and was heard as "flat and smooshed". Its loudness range is a fraction of theirs (2.4 LU against 5.6-16.4),
  short-term loudness sat at -7 LUFS from bar 1 to the end (the break dipped only to -8.8), and its side is 4-10 dB
  wider than theirs: width everywhere instead of space somewhere. "Ears" needs measures for these before the next try:
  section loudness contrast, transient punch per hit, the wet/dry ratio per section, and how much of the stereo field
  is reverb.
- **Matching a kick's band shape made it worse.** The layered kick reached the references' shape and was heard as a
  worse kick. Band levels do not capture what layering costs: the layers' own transients against the body's, phase
  between layers, and three distortion chains smearing the attack. Compare the hit's envelope and transient, not only
  its spectrum, and A/B each layer by ear-proxy before stacking.
- **More of the same chain is not harsher.** Pushing the kick bus COLDFIRE (Force into Wavefolder) from 30 % to 90 %
  wet made the kick darker (edge -25.5 to -28.5 dB). Harshness came from the layers' chains once a 325 Hz low-pass
  hidden in HW002's pad chain came off.
- **A +9 dB limiter on a flat arrangement flattens it further.** With the limiter doing the gain, the drop was no
  louder than the intro (-6.6 against -6.9 LUFS short-term).
- **HW002's chains were voiced for HW002.** Its kick EQ, Main fader, pad EQs and dark COLDFIRE settings all had to be
  found and undone; reusing them saved configuration but imported decisions made for another song.

## COLDFIRE from code

Live shows a plugin's knobs to the LOM only once they are configured (at most 128 per device, in the .als). HW002's
COLDFIRE instances are the VST2 build: 2312 parameters, in an order unlike the VST3's 277.

- `coldfire_vst3.json`: the VST3's parameters (names, ranges, value labels), read with pedalboard.
- `coldfire_vst2.json`: VST2 index by name, read back from Live with `coldfire.py probe` (a copy of the set where
  instance k shows indices 128k..128k+127) and `coldfire.py names`.
- `coldfire.py expose` makes every COLDFIRE in the set show 17 knobs (input, output, mix, colour, both distortion
  stages' type, drive, wet, output and filters). Live sends a shown knob's stored value to the plugin when the set
  loads, so it writes each instance's real values, parsed from the plugin's saved chunk (a Boost text archive of
  normalised values by internal name, e.g. `Distortion A_DistortionVariant_Drive 0.708`). The VST2 build shows raw
  0-1 values; module type is index/10 (Bit Crusher 0, ..., Force 0.5, ..., Transistor 1).

## Running it

```bash
cd hands
uv run python scripts/industrial/strip.py              # once: the set, from HW002_121_full.als, chains only
open -a "Ableton Live 12 Suite" ~/_agent_scratch/industrial/set/"INDUS_short Project"/INDUS_short.als
uv run python scripts/industrial/make.py build         # prune tracks instruments chains layers sounds notes mix master
uv run python scripts/industrial/coldfire.py expose    # (with the set saved and closed) COLDFIRE's knobs for the LOM
uv run python scripts/industrial/make.py render v8     # real time through a Resampling track, trimmed at beat 0
uv run python scripts/industrial/make.py stems [kickbus acid ...]
uv run python scripts/industrial/make.py snapshot scripts/industrial/set-v8.json
uv run python scripts/industrial/listen.py RENDER.wav --refs        # loudness per bar, band balance vs the refs
uv run python scripts/industrial/listen.py kickshape STEM.wav       # the kick's shape vs the refs' kick-alone bars
```

Notes from making it:

- Live renumbers auto-named audio tracks ("16-..." becomes "15-...") as tracks go: match them without the number.
- A source routed into another track's input is taken before its fader: gain goes on the receiving track.
- A real-time take's first ~0.9 s is off the timeline: the clips start after a 2-bar lead-in, trimmed at the take's
  own beat 0 (hands' `record_arrangement` and `trim_take`).
- Loading a sample onto an occupied Drum Rack pad replaces the sample and keeps the pad's effects.
- The acid stem: 252 of 325 notes on their written pitch by a harmonic-sum estimate; the misses sit just after a
  slide or an accent's filter sweep. A plain spectral-peak estimate reads the resonant harmonics instead.
