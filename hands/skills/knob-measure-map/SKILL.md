---
name: knob-measure-map
description: Build a "knob -> measure" map on a real Ableton Live set. Pick one device parameter on an instrument (e.g. a kick's distortion Drive), sweep it, bounce an isolated stem headless per setting, measure each (crest, sub_share, and the ears loudness bands), then assemble a param->measure acceptance curve. Use when asked to characterize how a knob affects a sound, instrument/sweep a device parameter, quantify drive/pitch/etc. against crest or sub_share, target the artist's real instruments, or extend the Meter->Critic->Assistant->Engineer pipeline in the autodaw/hands project. Covers safe copy-on-write cloning of real projects, target selection from the project library, offline .als analysis, and the Path-B isolated-stem bounce rig.
---

# Knob -> measure map (Ableton side)

This skill turns one device knob into a measured curve. You sweep the knob,
bounce isolated audio at each setting, measure it, and assemble
`{param -> measure}`. That curve is the "knob to measure" map: it says which
knob moves which measure, by how much, and where it stops being monotonic.

It is the Assistant rung of a four-rung ladder for Anthony's industrial /
techno production agent: Meter (names a sound's job) -> Critic (compares to a
corpus) -> **Assistant (suggest + apply a knob move with a reason)** ->
Engineer (render/measure/adjust loop). The map is what lets the Assistant turn
a measured gap into a specific knob move.

Proven end to end on THREE knobs of Anthony's real SNTS kick (`SNTS Style
track`, Kick (G) = track 6):

- **Decapitator (devices[1]) / Drive** — swept coarse (0..1, 11 steps) AND a
  finer 0.4..0.7 follow-up. NON-MONOTONIC: crest humps up (local max ~11.1 dB)
  and sub_share bottoms out near Drive 0.6. The finer sweep separates them: the
  crest peak sits at ~0.625 while the sub_share trough sits at ~0.6. Hard to
  invert; it is a grind / sub-thinning voicing knob, not a clean crest control.
- **StandardCLIP (devices[6]) / Clipping = threshold** — a CLEAN MONOTONIC crest
  control, nearly ORTHOGONAL to sub_share. This is the good crest lever.
- **kHs Transient Shaper (devices[3]) / Attack** — biggest crest range but
  sub-coupled (see `MAP.md`).

The assembled results (with an invertible target-crest -> threshold lookup for
the clipper) live in `~/sandbox/autodaw/hands/sweeps/MAP.md`. Read this skill top
to bottom, then execute.

## When to use

- "How does <knob> affect <sound>?" / "sweep <param> and measure it".
- "Get onto my real instruments" / target a real `.als`, not a synthetic test.
- Quantify drive/pitch/clip-threshold/etc. against crest or sub_share.
- Add a row to the knob->measure map, or extend the `autodaw/hands` pipeline.

## Companion skills and code (read/verify these exist first)

- **`ableton-live-control`** (`~/.agents/skills/ableton-live-control/`): how to
  drive Live. Path A = OSC (`scripts/live.py`, UDP 11000). Path B = LOM Python
  over MCP TCP 16619 (`hands live exec`). **This skill runs on Path B** —
  the isolated-stem bounce needs arbitrary LOM. Read its `reference/lom-guide.md`
  before writing LOM (the API crashes easily).
- **`virtual-display`** (`~/.agents/skills/virtual-display/`): optional, to keep
  Live off the user's physical screen. Needs BetterDisplay + TCC grants the
  user must click. If it is not set up, launching Live on the main screen is
  fine — OSC/MCP work regardless of window location, and the bounce is headless.
- **The runners + measurer** live in the `autodaw/hands` project at
  `~/sandbox/autodaw/hands/sweeps/` (paths below). The `hands` package
  (`~/sandbox/autodaw/hands/`) is the productionized Path-B consumer.
- **`HANDOFF.md`** (`~/sandbox/autodaw/hands/sweeps/HANDOFF.md`): running log of
  results and machine state. Append new findings there.
- **`MAP.md`** (`~/sandbox/autodaw/hands/sweeps/MAP.md`): the assembled
  knob->measure map itself, with inverse lookups for clean knobs. Append a new
  map row here whenever you characterize a knob (see step 8).

## The pipeline at a glance

```
target select  ->  clone (COW)  ->  launch Live on clone  ->  locate device/param
     ->  build bounce rig  ->  run_sweep_stem.py  ->  measure + assemble_curve.py
     ->  interpret + log
```

---

## 1. Pick a target (rich real project)

The "mothership" of Anthony's projects:
`/Users/anthonybecker/_tmsmsm/`. Real tracks live under
`Active Tracks/` and `daw-library/experimental projects/`.

Rank `.als` files by size — bigger usually means a richer, more-developed set.
`.als` files are gzipped XML, so size tracks complexity well. Exclude `Backup/`.

```bash
find "/Users/anthonybecker/_tmsmsm/Active Tracks" \
     "/Users/anthonybecker/_tmsmsm/daw-library" \
     -type f -iname "*.als" ! -path "*Backup*" -print0 2>/dev/null \
  | xargs -0 stat -f "%z	%N" 2>/dev/null | sort -rn | head -n 25
```

(macOS `find` has no `-printf`; use `stat -f` as above.) Skip template projects
(e.g. anything named "Template"). Named projects the user cares about (e.g.
HW002) are good candidates even if not the very largest.

### Choose the device offline (no Live needed)

`.als` is gzip. Decompress and inspect the track/device tree BEFORE launching
Live. This is fast and picks the exact target.

```bash
gzip -dc "SomeSet.als" > /tmp/set.xml
```

In the XML: tracks are `<MidiTrack>`, `<AudioTrack>`, `<GroupTrack>`,
`<ReturnTrack>`; names under `<Name><EffectiveName Value="..."/>`. Distortion
devices: native `<Roar>`, `<Saturator>`, `<Overdrive>`, `<DynamicTube>`,
`<Amp>`, `<Redux2>`; plugins under `<PluginDevice>`/`<Vst3PluginDevice>` (read
the plugin name). **Track order in the XML == Live's `song.tracks[i]`**
(0-based, group tracks included as their own entry).

**Delegate this to a sub-agent** when scanning several files — it decompresses,
greps, and returns a concise target recommendation (file, track index+name,
device index+name, param name) instead of dumping XML.

### What makes a good first target

- A **standalone track** (not a group), so an isolated stem tap has no
  siblings bleeding in. A kick group bus sums kick + rumble — avoid it first.
- **One clear knob** (a single saturation/clip stage), not many interacting
  devices. Bypass or ignore the rest.
- Note: VST param names are NOT in the `.als` — enumerate them live (step 4).
- Note: devices are often bypassed (`On=false`) — you must enable the target.

---

## 2. Clone the project copy-on-write (NEVER touch the original)

Open a COW clone, never the artist's real file. On APFS `cp -Rc` is instant and
uses no real disk; edits to the clone can't affect the original. Clone the whole
project folder so `Samples/` stay linked (the instrument needs them).

```bash
mkdir -p "/Users/anthonybecker/_agent_scratch"
cp -Rc "/Users/anthonybecker/_tmsmsm/.../PROJECT_FOLDER" \
       "/Users/anthonybecker/_agent_scratch/PROJECT_FOLDER"
```

You then operate on the clone in memory and **never save**. Even a crash leaves
the original untouched.

---

## 3. Launch Live on the clone, verify Path B

Live must not already be running (it opens fresh). Check first:
`pgrep -fl "Ableton Live"`. Then:

```bash
open -a "Ableton Live 12 Suite" "/Users/anthonybecker/_agent_scratch/PROJECT_FOLDER/THE_SET.als"
```

A large set can take 30-60s to load. Poll for Path B (MCP, TCP 16619):

```bash
for i in $(seq 1 30); do nc -z 127.0.0.1 16619 && echo up && break; sleep 5; done
```

Then confirm it really responds and the set loaded:

```bash
cd <zpkt>/hands
uv run hands live exec --json "result = {'tempo': song.tempo, 'names': [t.name for t in song.tracks]}"
```

Notes:
- **OSC (11000) is UDP** — `nc -z` cannot test it reliably; use
  `bash scripts/osc_up.sh` if you need Path A. Path B is enough for this skill.
- If MCP never comes up, the `AbletonLiveMCP` control surface isn't selected
  (see the `ableton-live-control` setup). Both control surfaces persist in
  Live's prefs across restarts.

---

## 4. Locate the target device and its parameter (live)

Find the track index from the names list. Then inspect its device chain and the
target device's parameters. Confirm the offline pick.

```bash
cd <zpkt>/hands
# device chain of the target track (find the distortion + its on-state)
uv run hands live exec --json "tr=song.tracks[6]; result=[{'i':i,'name':d.name,'class':d.class_name,'on':d.parameters[0].value} for i,d in enumerate(tr.devices)]"
# parameters of the target device (find the knob, e.g. 'Drive')
uv run hands live exec --json "d=song.tracks[6].devices[1]; result=[{'i':i,'name':p.name,'val':p.value,'min':p.min,'max':p.max} for i,p in enumerate(d.parameters)]"
```

Parameter 0 is always `Device On`. For Decapitator the knob is `Drive`;
Saturator/Roar also use `Drive`. Check `AutoGain`/makeup-gain params are OFF, or
they will mask the effect.

---

## 5. Build the bounce rig (Path B / LOM)

**Fast path (recommended): one idempotent command.** `build_rig.py` does the
whole rig in a single re-runnable step — it discovers the trigger notes, creates
the capture track (tapping the source) and the looping session clip in the
source's slot 0, and creates ONLY the pieces that are missing:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/build_rig.py --source "Kick (G)"          # build/repair
uv run python sweeps/build_rig.py --source "Kick (G)" --check  # report only, mutate nothing
```

`--source` takes a track name or index; `--check` prints the rig state (source
and capture indices, discovered notes, whether the session clip and routing are
in place, and `rig_ready`) without changing anything. Other flags: `--notes`
(`auto` or a comma list like `2,4`), `--loop-beats`, `--capture-name`,
`--clip-name`, `--source-input`. It follows the LOM crash rules internally, so
prefer it over hand-copying the sequence below.

The rest of this section is the manual LOM sequence — keep it as the explanation
of what `build_rig.py` does, and as a fallback if the builder can't run.

The runner `run_sweep_stem.py` records an ISOLATED stem: it taps the source
track's output into an empty audio "capture" track, plays the source's SESSION
clip slot 0, and arrangement-records the tap. A real arrangement set has neither
a spare capture track nor a session clip, so build them. Follow the LOM crash
rules (write, then read in a SEPARATE call; sleep ~0.3-0.4s between mutating
calls; re-fetch `song.tracks[i]` after create/delete).

**a) Create + route a capture audio track.** Tap = the source track by name.
Only stereo channels ("1/2") are offered; that's fine — **crest and sub_share
are gain-invariant, so a post-mixer tap is valid** (a constant fader scales peak
and RMS together and cancels out).

```python
# call 1: create
song.create_audio_track(-1); result='created'
# call 2 (after sleep): route the new last track to tap the source
i=len(song.tracks)-1; tr=song.tracks[i]; tr.name='STEM_CAP'
rt=next(r for r in tr.available_input_routing_types if r.display_name=='Kick (G)')
tr.input_routing_type=rt
result={'idx':i,'in':tr.input_routing_type.display_name}
```

**b) Discover the trigger notes.** The source is usually a Drum-Rack MIDI track;
find which pad note(s) fire the sound from its first arrangement clip.

```python
c=song.tracks[6].arrangement_clips[0]
ns=list(c.get_notes_extended(0,128,0,8))
result=sorted({n.pitch for n in ns})   # e.g. [2, 4] -> both pads layer the kick
```

**c) Create a looping session clip** on the source track, slot 0, replaying that
pattern (a 4-beat 4-on-4 loop is a good default). Use `add_new_notes(tuple(...))`
— a plain tuple, NOT a dict, and `MidiNoteSpecification` is a Path-B global.

```python
# call 1: create the empty clip
song.tracks[6].clip_slots[0].create_clip(4.0); result='clip'
# call 2 (after sleep): fill + loop it
c=song.tracks[6].clip_slots[0].clip; c.name='STEM_KICK_4on4'
notes=[MidiNoteSpecification(pitch=p, start_time=float(b), duration=0.25, velocity=100)
       for b in range(4) for p in (2,4)]
c.add_new_notes(tuple(notes)); c.looping=1; result='notes'
```

Firing a session clip OVERRIDES that track's arrangement, so only the source
plays into the tap. Other tracks' arrangement audio is not captured.

**d) Enable ONLY the target device** (leave other FX bypassed for a clean
single-variable curve). Param 0 is `Device On`.

```python
song.tracks[6].devices[1].parameters[0].value=1.0; result='on'
```

---

## 6. Write the sweep spec and run

The spec (`*.sweep.json`) is the stable IN contract. Required keys:
`sweep_id, device_expr, param_name, start, stop, steps`. Useful extras:
`unit, bounce_beats, settle_seconds, predicted_measure, predicted_direction,
hypothesis, output_dir, restore`. Example lives in this skill at
`examples/snts_kick_decap_drive.sweep.json`.

```json
{
  "sweep_id": "snts_kick_decap_drive_v1",
  "device_expr": "song.tracks[6].devices[1]",
  "param_name": "Drive",
  "start": 0.0, "stop": 1.0, "steps": 11,
  "bounce_beats": 8, "settle_seconds": 0.4,
  "predicted_measure": "crest", "predicted_direction": "decreasing",
  "output_dir": "out/snts_kick_decap_drive_v1"
}
```

Run the isolated-stem runner, pointing it at the source track, its input name,
and the capture track index you created:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/run_sweep_stem.py \
  --sweep sweeps/snts_kick_decap_drive.sweep.json \
  --source-track 6 --source-input "Kick (G)" --capture-track 44
```

It sets the knob, reads back the true value, bounces `bounce_NNN.wav` +
`bounce_NNN.params.json` (the OUT handshake pair), and restores the param at the
end. It is resumable (skips rows that already have a wav + sidecar).
`--no-restore` leaves the last value set. Non-silent bounces are ~0.9 MB;
a silent bounce means the rig routing or the session clip is wrong.

**The `--capture-track 44` and `--source-track 6` above are SPECIFIC to the SNTS
set/session** (capture index 44 is where the rig track happened to land). On any
other set, discover both fresh — e.g. `build_rig.py --source <name> --check`
reports the source and capture indices for you.

### One-shot: run + assert-nonsilent + assemble (`sweep.sh`)

Once the rig is up, `sweep.sh` runs the whole loop in one command: it runs the
isolated-stem sweep, ASSERTS every bounce is non-silent (fails loudly if the
routing/session clip is wrong), then assembles + measures the curve with the
full canonical band set and prints the aligned view.

```bash
cd ~/sandbox/autodaw/hands
bash sweeps/sweep.sh --sweep sweeps/snts_kick_clip_thresh.sweep.json \
  --source-track 6 --source-input "Kick (G)" --capture-track 44
```

Extra args pass through to `run_sweep_stem.py` (e.g. `--no-restore`). Env knobs:
`MEASURER` (see §7 — point it at the real ears shim) and `MIN_WAV_KB` (silence
threshold). Same SNTS-specific track indices caveat applies — discover them
fresh on any other set.

`run_sweep_stem.py` also accepts an explicit `values` array in the spec, used
VERBATIM instead of `start`/`stop`/`steps`. Duplicates are kept, so a spec like
`"values": [0.75, 0.75, 0.75, 0.75, 0.75]` is how you measure run-to-run noise.
It also FAILS FAST on a silent or tiny bounce (`--min-wav-kb`, `--min-peak-dbfs`,
escape hatch `--allow-silent`), deleting the dead wav instead of writing a dead
row.

Use `rig.py` rather than toggling devices by hand:

```bash
uv run python sweeps/rig.py snapshot   --track 6 --name snts_kick_devices
uv run python sweeps/rig.py solo-device --track 6 --device 6 --name my_rig
uv run python sweeps/rig.py restore    --from sweeps/snapshots/snts_kick_devices.json
```

`restore` re-reads every value and exits nonzero on mismatch, so "I restored it"
is verified, not assumed.

---

## 7. Measure + assemble the curve

**The measurer of record is the real `ears` lab, reached through the IN-REPO
shim.** Use this:

```bash
export EARS_CMD="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/ears"
--ears-cmd "uv run python sweeps/ears_shim.py"
--measure-keys crest_db sub_share low_share mid_share high_share air_share
```

Why a shim, not bare `ears`: real `ears` returns `loudness.band_energy["sub"]`
(NESTED, not a flat `sub_share`) and has NO crest metric at all, so
`--ears-cmd "ears"` cannot feed this pipeline.

Why the IN-REPO shim specifically: the lab lives in `_agent_scratch`, which is
DISPOSABLE. `sweeps/ears_shim.py` is in the repo, so it always exists. If
`$EARS_CMD` resolves, it uses real ears' band shares (corpus-exact); if not, it
falls back to `measure_local`'s band math, which is validated to agree to
3.2e-08. The pipeline therefore never breaks — it only loses corpus exactness,
and it TELLS you which happened via its `measurer` field:

```
"ears_shim (real ears band shares + local crest_db)"   <- lab was reached
"ears_shim (canonical band shares + crest_db)"          <- fell back
```

Check that field. Do not assume you got the lab.

There is also a lab-side shim at
`/Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py`, which is what built
the existing `*.acceptance.ears.csv` files — that is why their crest column is
named `crest` rather than `crest_db`. Same numbers, but it dies with
`_agent_scratch`.

**Pure-offline fallback: `measure_local.py`** (in-repo, no lab needed):

```
--ears-cmd "uv run python sweeps/measure_local.py"
--measure-keys crest_db sub_share low_share mid_share high_share air_share
```

The two are VALIDATED to agree: every sweep re-measured both ways, worst
disagreement 3.2e-08 against a 1e-6 budget, and crest identical bit-for-bit.
The ~1e-8 residual is float32-vs-float64 FFT input rounding, not different math.
`test_measure_agreement.py` fails the build if they ever drift. Details in
`sweeps/PHASE1_REPORT.md`.

NEVER use `lufs_*` or `true_peak` on stem taps. They are gain-dependent and our
taps are gain-scaled, so those numbers are meaningless; they are real only on
properly-leveled full mixes.

Always request the FULL five-share set, not just the one you predicted. The
shares are gain-invariant and they show WHERE energy moved, not merely that
crest changed:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/assemble_curve.py \
  --dir sweeps/out/snts_kick_decap_drive_v1 \
  --ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py" \
  --measure-keys crest sub_share low_share mid_share high_share air_share \
  --out sweeps/out/snts_kick_decap_drive_v1/snts_kick_decap_drive_v1.acceptance.ears.csv
```

Then let the tool read the curve for you instead of eyeballing it:

```bash
uv run python sweeps/summarize_curve.py \
  --csv sweeps/out/snts_kick_decap_drive_v1/snts_kick_decap_drive_v1.acceptance.ears.csv
```

It reports direction, extrema and where they sit, span, and the largest
strictly-monotonic (invertible) region — which is exactly what a `MAP.md` row
needs. Pass `--tol 0.02` to judge direction against the measured crest error bar
rather than a fraction of the span.

This writes `<sweep_id>.acceptance.csv` AND a pre-aligned `.acceptance.txt`.
**Read the `.txt` view, do NOT `column -t` the CSV** — for a VST the
`value_string` column is blank, and `column -t` collapses the missing field and
shifts every measure column one to the left. The `.txt` renders blanks as `-` so
they can't be misread:

```bash
cat sweeps/out/snts_kick_decap_drive_v1/snts_kick_decap_drive_v1.acceptance.txt
```

`assemble_curve.py` now RESOLVES the loosely-named `predicted_measure` (e.g.
`crest`) to the real column that holds it (`crest_db`), so the monotonicity
verdict actually fires instead of the old false "no measured column". On a
non-monotonic curve it also prints a `Refine:` line proposing a finer sweep
window around the interior extremum (the "sweep the hump, not the ends" lesson,
automated).

---

## 8. Interpret and log

- **Sweep the WHOLE range, not just the ends.** Real distortion/pitch knobs are
  often NON-MONOTONIC. On the SNTS kick, `drive -> crest` fell net end-to-end
  (9.82 -> 8.14 dB) but humped UP to 11.10 dB at Drive 0.6; `drive -> sub_share`
  bottomed at 0.56 at the same 0.6. Endpoints alone hide the hump.
- **Pick a range that CROSSES the band edge you measure.** A 49 Hz kick swept
  +/-10 st stayed inside the 20-150 Hz sub band, so `sub_share` saturated flat.
  Flat != result; it means the range never crossed 150 Hz.
- **Watch for reversals vs the research register.** Sampled-kick
  `pitch -> sub_share` measured DECREASING though the register predicted
  increasing. Log measured signs as documented reversals.
- **Prefer clean, orthogonal knobs for control.** On the SNTS kick, Decap Drive
  is non-monotonic (crest hump ~0.625, sub_share trough ~0.6 — they separate at
  finer resolution) and hard to invert, while the StandardCLIP threshold is a
  clean monotonic crest control nearly orthogonal to sub_share. When a knob is
  clean and monotonic, record an inverse lookup (target measure -> knob value).
- Append the result to BOTH logs: the map row (curve shape, range, spectral side
  effect, and any inverse lookup) to `~/sandbox/autodaw/hands/sweeps/MAP.md`, and
  the finding + machine state to `~/sandbox/autodaw/hands/sweeps/HANDOFF.md`
  section 4.

---

## 9. Safety rules (do not skip)

- **Always work on a COW clone; never save the artist's real set.** The original
  must be byte-for-byte untouched.
- **Restore every param you change.** The runner restores the swept param. You
  must also restore any device `On` state you flipped, and remove the helper
  capture track + session clip if you want the clone pristine (optional — the
  clone is disposable).
- **Never restart or quit Live with unsaved work you care about** — an unsaved
  built set is lost on close. (For a clone that's fine; it rebuilds.)
- **Prefer OSC/text over screenshots.** Retina virtual-display shots are ~15 MB;
  crop/downscale before reading one. Almost all state is available via LOM/OSC.
- If you used a virtual display, move Live back on-screen BEFORE destroying it.

## 10. Cleanup / teardown

- Restore the target device `On` to its original value.
- `song.tracks[6].clip_slots[0].delete_clip()` and
  `song.delete_track(<capture_idx>)` to remove the rig (optional).
- Quit Live and delete the clone under `/Users/anthonybecker/_agent_scratch/`
  when done, or leave the rig up for follow-up sweeps (finer range, next knob).

## File map (in `~/sandbox/autodaw/hands/sweeps/`)

- `build_rig.py` — idempotent Path-B rig builder (`--check` reports state); the
  one-command replacement for the manual step-5 LOM sequence.
- `run_sweep_stem.py` — the reliable Path-B isolated-stem runner. USE THIS.
- `sweep.sh` — one-shot loop: run + assert-nonsilent + assemble/measure.
- `run_sweep.py` — older resampling runner; flaky on this machine.
- `run_sweep_osc.py` — Path-A runner (top-level params; optional osascript bounce).
- `measure_local.py` — offline fallback measurer (canonical band shares, crest_db).
- `ears_shim.py` — canonical-key measurer adapter; **the `--ears-cmd` to use**
  (auto-upgrades to real `ears` via `$EARS_CMD`, falls back to `measure_local`).
- `assemble_curve.py` — joins sidecars + measurer into an acceptance CSV/TXT;
  resolves the predicted-measure column and suggests a refine window.
- `summarize_curve.py` — reads an acceptance CSV and reports direction,
  extrema + where, span, and the invertible region(s). Use instead of eyeballing.
- `compare_measurers.py` — max abs diff per column between two acceptance CSVs.
- `test_measure_agreement.py` — regression test; fails if ears and
  `measure_local` drift past 1e-6 on a fixed reference bounce.
- `rig.py` — device `snapshot` / `solo-device` / read-back-VERIFIED `restore`.
- `snapshots/snts_kick_devices.json` — track 6 original-state restore target.
- `PLAN.md` — the five-phase tidy-first plan. `STATUS.md` — what is actually done.
- `PHASE1_REPORT.md` — the ears-vs-`measure_local` validation write-up.
- `*.sweep.json` — sweep specs, incl. `snts_kick_decap_drive.sweep.json`,
  `snts_kick_decap_drive_fine.sweep.json`, `snts_kick_clip_thresh.sweep.json`.
- `out/<sweep_id>/` — bounces + curves (e.g. `out/snts_kick_decap_drive_fine_v2/`,
  `out/snts_kick_clip_thresh_v1/`).
- `MAP.md` — the assembled knob->measure map + inverse lookups (this folder).
- `HANDOFF.md` — authoritative context + results log.
