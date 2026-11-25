# The HW002 arranger

A phone page for trying arrangements of HW002 out of loops bounced from Live, and the pages after it. Each page
writes structure into the arrangement file, and the structure adds up to a recipe that the mastering step runs in
Ableton Live (Anthony, 12 November 2026: "All of this accumulates into a recipe for the mastering step to actually run
in ableton live").

| Step | Page | Writes | How it is heard |
|---|---|---|---|
| Arrange | `/` | `regions` | Loops bounced from Live, started together in the browser |
| Transitions | `/transitions/` | `transitions` (picks, levels, Live recipes) | Sounds made in Live, started over the loops |
| Mix 1: gain, pan, EQ cuts | `/mix/` | `mix` (per channel) | The same files through a gain, a pan and cuts in the browser, set one sound at a time and A/B'd against the reference tracks |
| Mix 2: distortion, EQ boosts, compression, bus processing | `/mix2/` | `mix2` (kept devices and settings, in order) | Small batches rendered in Live: Anthony picks the ranges, `mixset.py` renders a coarse grid of them in the mix set, he plays the grid in the page |
| Spectrum against the references | `/spectral/` | `spectral` (fixes kept, each a gain move or devices with values) | `spectral.py` compares the mix's spectrum with the four HW002 references, fixes the five biggest differences in Live and renders each; the page A/Bs them against the mix and the references |
| Kick design | `/kick/` | `kickFuzz` (the kick kept) | Kicks only, A/B/C on the beat, on the phone: HW002's kick options rendered through its own chain (`kickfuzz.py`) against the references' own kick bars (`kickdesign.py`), with each kick's spectrum moving as it plays |
| Master | not built yet | | Runs the whole recipe in Live |

Three ways to hear a change: offline DAW audio (renders), online browser audio (the first three steps, within the
named exceptions in `contrib/docs/sound.md`), and, for the second mix step, online small-batch DAW audio.

1. `uv run python contrib/arranger/bounce.py` solos each part of the set in Live and exports Main
   (15 bounces, about 6 minutes). Live must have the working copy `HW002_121_pp_loops` in front.
2. `uv run --extra audio python contrib/arranger/mine.py` cuts those bounces into loops and one-shots on the bar,
   writes `loops.json`, and checks the song's own arrangement, summed, against Live's bounce of the mix.
3. `python3 contrib/arranger/server.py` serves the pages on 127.0.0.1:8975 (`ARRANGER_PORT` to change it);
   `tailscale serve` puts it on the tailnet.

The page starts the loops together on the bar clock and does nothing else to them (`contrib/docs/sound.md`: the
browser plays renders, it never makes sound). What it produces is a structure, not audio: each saved arrangement
names its loops by stem and source bar, so it can be rebuilt in the set and rendered in Live.

`shorts.py` writes the one-minute arrangements shown as tabs (the canonical 8d2a2; it replaces the file, later
steps included), and `uv run --extra audio python contrib/arranger/measure.py short-8d2a2` prints a tab's level
above 6 and 10 kHz for each four bars, and its peak.

### Where the data is, and what a save keeps

I keep the audio, the renders and the saved arrangements outside the repo, in `$ARRANGER_DATA` (default
`~/_agent_scratch/arranger`). Every script and the server read that one folder, whichever checkout they run from.
The mix desk (`contrib/mixdesk/recipe.py`) reads the same variable with the same default, and writes its `desk` key
into the same `arrangements/short-8d2a2.json`. So the arranger and the desk share one recipe file only when both
run with the same `ARRANGER_DATA` (by default they do).

The arrangement file is the recipe. Each page owns its keys: the arranger page `name, bars, regions, mutes`; the
others `transitions`, `mix`, `mix2`, `spectral`, `kickFuzz`; the mix desk `desk`. A save from the arranger page keeps
every key it does not own, so editing the arrangement never drops a later step or the desk. Its shape is
`lib/contracts/arrangement.schema.json`; `arrangement.py` is the code that parses it. Its type names two halves,
`Structure` (regions and transitions, with the page's name, bars and mutes) and `Sound` (mix, mix2, spectral,
kickFuzz, desk); in the file their keys stay side by side, as they always were.

### How it is built

| File | What it is |
|---|---|
| `server.py` | The pages and their files: a table of routes grouped by page, each a short function. `make_server(data, port=...)` starts it anywhere. |
| `arrangement.py` | The arrangement's typed shape, the one parse of each body a page sends, and what a save keeps. Pure. |
| `hw002.py` | What every script shares about HW002: tempo, bar, the 40-bar span and the drop at bar 17, the set names, the data folder, and `live_ops` (hands' LiveOps for these sets). |
| `bounce.py`, `mine.py`, `shorts.py`, `measure.py`, `refs.py` | The loops, the tabs, and the references for mix 1. |
| `fxset.py` | The transition sounds, made in a copy of the set. |
| `mixset.py`, `spectral.py` | The mix set, mix-2 batches, and the spectrum against the references. |
| `renderqueue.py` | The mix-2 render queue: the request files, the worker's order, and where the queue stands (`GET /api/mix2/queue`). |
| `kickfuzz.py`, `kickiso.py`, `kickdesign.py`, `kicktexture.py`, `kickshape.py` | The kick options and their measures. |

Each script is a few library functions and a thin command at the bottom. Nothing changes the environment at import:
hands' rig settings are pointed at the HW002 sets only when a command asks for Live (`hw002.live_ops`).

### Tests

Offline, in hands' environment plus scipy and pyloudnorm for the measuring scripts:

    uv run --all-extras pytest -q contrib/arranger/tests     # from the repo root

They start the server in-process on a free port against a temporary data folder and call every route over HTTP;
replay the scripts' Live steps against a stand-in for LiveOps and compare them with goldens in `tests/golden/`;
and run the measuring scripts on made-up audio. Nothing talks to Live. A golden is rewritten only on purpose, with
`ARRANGER_GOLDEN=write`, when the behaviour is meant to change.

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

## Mix 1

`/mix/` is a row of small cards, one decision each (a sound's level, then its pan, then its cuts; the kick only level
and cuts), swiped left to right, with a strip of them along the top grouped by sound (the mini map) and a map of the
whole process (the recipe's steps, then every sound with its decisions). The listening options fold into one line,
and the curves show only on the cuts cards and the whole mix. The cards are a ladder: the sounds from the most fundamental up (kick, chord, the break parts, the hats in the order the
ramp brings them in, crash and splash, the transitions), each set on its own card against the ones above it, and a last card for the whole mix against a
reference. The view
loops the bars where the sound matters, plays what is set so far under it (or everything, or it alone), and asks for
level, then pan, then cuts; the suggested cuts come from where the sound's average spectrum sits close under the
strongest bands of the sounds above it. One A/B button switches on the next beat between before and after, without
and with, or the mix and a reference track. A reference plays at its own tempo from the same place relative to the
drop (8d2a2's bar 17 is the reference's drop, as wav-timeline finds it), turned to the mix's loudness over the same
bars (K-weighted, a listening aid), and switching back picks the mix up where the reference has got to. The curves are
measured from what plays: the sound, what is under it, the whole mix, and the reference at the same place.

`uv run --extra audio python contrib/arranger/refs.py` prepares the references (the four HW002 references and the
Klangkuenstler shorts: tempo and drop from wav-timeline's own analysis, the 40 bars around the drop, K-weighted power
per bar, a spectrogram) and the average spectrum of each sound, in `~/_agent_scratch/arranger/refs/`.

## Mix 2

`/mix2/` asks for a batch: a channel or a bus, a Live device (Saturator, Drum Buss, EQ Eight as a boost, Compressor,
Glue Compressor), one or two of its parameters with a range and a number of steps (or a few of its settings), and a
stretch of bars. The server queues it and starts `mixset.py worker`, which renders it in Live and stops at the first
surprise (the batch then shows why it failed). Live must have `HW002_121_pp_mix` in front.

The renders come from the mix set, `HW002_121_pp_mix.als`, built by `mixset.py build` from the arrangement file: one
audio track per mix channel with the loops and picked transitions where the arrangement puts them, routed to a bus per
group, mix 1 on the mixers and an EQ Eight, and a -6 dB Utility on Main for headroom. Built that way, every bar
without a transition matches the page's own sum to 0.0 dB. Each batch renders the mix as it stands (mix 1 and every
kept mix-2 choice), then each grid point twice: as it comes out, and with Main turned to the first render's loudness
(integrated LUFS), so a louder setting does not win by being louder. The page plays the renders and switches between
them on the bar; Keep writes the point into the arrangement's `mix2`, and later batches are rendered with it.


## Spectrum against the references

`spectral.py` renders the mix as the recipe stands (`before`), measures its long-term spectrum in 48 log bands, its
width per range (side against mid) and its peak-to-loudness, over the build (bars 1-16) and the drop (17-32), against
the same windows of the four HW002 references (their drop lined up with bar 17), each curve relative to its own
loudness so the comparison is shape, not level (`analyze`). The five biggest differences and a fix for each are
written by hand into `DATA/spectral/fixes.json`: a mix-1 gain move or a Live device with its values on a channel, a
bus or Main. `after` renders each fix alone and all of them together; `measure` writes what the page plays.

`/spectral/` plays any two of those renders or a reference as A and B, switching on the beat at the same place in the
music, over the build, the drop or all 40 bars, matched in loudness over the drop as a listening aid. It draws the
drop's spectrum of A and B against the references' range, and each difference as a card: what was measured, why it
matters, the fix, and what the fix did. Keep writes the fix into the arrangement's `spectral`; `mixset.py` applies kept
fixes after mix 2, and `spectral.py` renders `before` without them.

### Kick fuzz and the references' isolated kicks

`kickiso.py` isolates the references' kicks by the beat. Each of the drop's 64 beats is lined up on its kick onset.
The median spectrogram over the beats keeps what repeats on every beat, and the slice from the onset to the next
sixteenth is the kick. It does the same to our mix, and to our kick loop alone, which checks the method: below 4 kHz the
two agree to within 1 dB, while above 5 kHz on-beat hats leak in. `kickiso.py match` fits an EQ Eight to the gap
between ours and the references' average.

`kickfuzz.py` makes kick options from HW002's own kick chain, in `HW002_121_pp_loops`. Every touched value is put back
before the set is left. The options:

- the hidden 3.4 kHz cut and 325 Hz low-pass off;
- the 052 fuzz layer up;
- the kick group's multiband Roar on;
- the rumble's Decapitator driven.

Each option is bounced as `bounce.py` would and cut like `kick-rumble-a`. In the mix set the kick channel's clips are
swapped for it and the channel is turned by the loop's loudness change, then the 40 bars are rendered. `match`
renders the fitted EQs on the kick channel, with the loudness matched by soloing the kick in Live. `measure` isolates
the kick from every mix for the page.

The page's Kick fuzz tab A/Bs the mixes and the kick loops alone. Keep writes the arrangement's `kickFuzz` (the loop,
the gain, and the EQ if there is one), and `mixset.py` applies it.

### The kick design page

`/kick/` shows kicks only. There are three slots, A, B and C. Tapping a slot switches to it on the next beat, and the
row of kicks under the slots fills the selected one. HW002's kick options (from `kickfuzz.py`) sit beside two bars
cut from each HW002 reference where its kick plays nearly alone. `kickdesign.py` finds those bars by the beat: every
beat must open with a kick, and the score is how quiet the rest of the beat is above 300 Hz, so the kick's own fuzz
doesn't count against it. Each stretch agrees with the same reference's kick isolated from its drop (`kickiso.py`)
to within 1 dB on three of the four.

`kickdesign.py` works out every kick's spectrum on the Mac, 86 frames a second in 72 bands. The page draws the
playing kick's curve at the playing moment, its average, the other two slots at the same place in the beat, and the
references' kicks as a band. When stopped it previews the selected kick's first beat. The page cannot be zoomed.

### Kick texture (KSMS is the canonical reference)

Anthony heard every fuzz option as "basically a soft noise, like an echo of a stick hit", where KSMS is "fuzzy and
compressed". `kicktexture.py` measures a kick's mid-highs (1-6 kHz) over its median beat:

- how long they hold within 12 dB of their peak;
- how much is left 100-170 ms after the hit, before HW002's offbeat pad;
- how noise-like their spectrum is (flatness);
- the crest of their envelope (how compressed they are);
- their share of the kick's energy.

It also gives a distance to KSMS. Our loops are read on their exact grid. An onset search locks onto the rumble's
swell between kicks.

HW002's kick as it is clicks: its mid-highs are gone in 8 ms. The 052 layer is high-passed at 958 Hz *before*
COLDFIRE, so COLDFIRE only ever saw the click. What matches KSMS's texture is fuzz made from the body. The kick
group's multiband Roar clips the low band (Tri Fold, 24 dB drive), a high-pass after the shaper keeps only what the
clipping adds above 600 Hz, and that is blended 35 % under the clean kick and compressed (`t-f1`). Roar on the whole
group or on the kick track fuzzes the long boom or the rumble too, and never stops.

`kickiso.py match` then fits the whole spectrum to KSMS's isolated kick (`mf1`). The deep sub (30-50 Hz) stays about
11 dB short whatever the EQ does, and easing HW002's 30 Hz shelves doesn't bring it back. It looks like a
sound-design difference: our rumble is ducked under each kick, and KSMS's sub sits on the hit.
