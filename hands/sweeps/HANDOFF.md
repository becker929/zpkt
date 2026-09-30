# Handoff: the knob to measure map (Ableton side)

Written 2026-09-08 (turn 4), by the outgoing agent. I hold both the
research context and the Ableton build context. This doc carries both,
then tells you exactly what to do next. Read it top to bottom once.

---

## 1. The mission (why any of this exists)

Anthony makes industrial / hard techno. We are building an agent that
helps him produce it. Not by generating music. By MEASURING sound
against a corpus, then driving his instruments to close the gap.

The plan is a four-rung ladder:

- Meter — names a sound's job. Exists.
- Critic — compares a mix to corpus norms. Mostly ready.
- Assistant — suggests + applies a knob change with a reason. THIS.
- Engineer — render / measure / adjust loop overnight. Later.

The Assistant needs one thing first: the "knob to measure" map.
That map says which knob moves which measure by how much. To learn it
we sweep one knob, bounce the audio, measure it, record the row.
Ableton access is the unlock. That is what this folder does.

## 2. Status in one paragraph

The full loop is closed and proven: build an instrument, set a knob,
bounce isolated audio, measure it, assemble a curve. Both control
paths to Live are up. We have the first validated result on a
plugin-built kick. The remaining gaps are real-world, not plumbing:
we need Anthony's actual instruments and the real measurement lab.

## 3. What is proven (works today)

- Path A (OSC): set + read back any top-level device param. Fast, safe.
- Path B (LOM/MCP): arbitrary Live API code. Loads devices, records.
- Build a plugin instrument from a JSON config (Drum Rack + Simpler).
- Bounce an ISOLATED stem headless (no GUI) over Path B.
- osascript native export also works, but needs a UNIQUE filename and
  Live off-screen. Prefer the Path-B stem bounce; export is a backup.
- Measure the bounce locally with `measure_local.py`.
- Assemble a `{param -> measure}` acceptance curve with a verdict.

## 4. The findings so far (real results, log these)

On the plugin kick (Simpler "Kick 49 Hz", swept `Transpose`):

- pitch -> sub_share is monotonic DECREASING.
  `out/kick_pitch_wide_v1/` (0..+36 st). sub_share 0.9996 -> 0.0023.
  Sharp cliff at +18 -> +21 st, where the 49 Hz fundamental crosses
  the 150 Hz sub-band edge and energy jumps into the low band.
  THIS IS A REVERSAL. The register predicted INCREASING. The measured
  sign for a sampled kick is DECREASING. Put it in the hypothesis
  register as a documented reversal.
- pitch -> crest is monotonic INCREASING (5.23 -> 13.83 dB).

Sweep-design lesson (important): the FIRST run `out/kick_pitch_v1/`
(-10..+10 st) showed sub_share FLAT at ~0.999. That was not a result.
+/-10 st on a 49 Hz kick stays 27-87 Hz, all inside the sub band, so
the measure could not move. Always pick a range that CROSSES the band
edge you are measuring.

FIRST REAL-INSTRUMENT RESULT (turn 5): Anthony's own `SNTS Style track
2026-04-21` (opened as a copy-on-write CLONE, never saved). Kick (G) =
track 6 (standalone Drum-Rack MIDI track). Swept the `Drive` of its
**Decapitator** (VST3, devices[1]), 0..1 in 11 steps, Style fixed at
0.5, AutoGain off. `out/snts_kick_decap_drive_v1/` (measure_local).

- drive -> crest is NON-MONOTONIC. Net DECREASING across the full range
  (9.82 dB at 0.0 -> 8.14 dB at 1.0, ~-1.7 dB), but with a HUMP: crest
  RISES to a local max 11.10 dB at Drive 0.6, then falls hard to 1.0.
  The naive "more drive squashes peaks -> lower crest" only holds in the
  UPPER half (0.6 -> 1.0). Below 0.6 it is flat-to-rising.
- drive -> sub_share DROPS from 0.752 to a MINIMUM 0.557 at Drive 0.6
  (added upper harmonics pull energy out of the sub band), then
  partially recovers (0.73 at 0.8) and dips again to 0.63 at 1.0.
- Drive ~= 0.6 is a shared inflection: sub_share bottoms and crest peaks
  at the SAME setting. A real coupling on this kick, and exactly the
  knob->measure structure the map is meant to catch. Worth a finer
  sweep of 0.4..0.7 to resolve the hump.
- Lesson echoed: a real distortion knob is NOT monotonic against a
  simple measure. The endpoints alone would have hidden the hump. Sweep
  the whole range, not just the ends.

Caveats: measure_local (provisional crest; canonical sub_share). Result
is for Decapitator Style=0.5; other styles will move the curve. The kick
tap was post-mixer stereo, which is fine because crest and sub_share are
gain-invariant.

FINER SWEEP TO RESOLVE THE 0.6 HUMP (turn 6): re-ran the SAME rig
(SNTS clone still open, STEM_CAP = track 44, only Decapitator enabled,
Style=0.5, AutoGain off) at 0.025 resolution across Drive 0.4..0.7,
13 steps. `out/snts_kick_decap_drive_fine_v2/` (spec
`snts_kick_decap_drive_fine.sweep.json`). Findings:

- sub_share is a CLEAN, SMOOTH U in this window. It falls monotonically
  0.691 (0.4) -> MINIMUM 0.5578 at Drive 0.6, then rises smoothly back
  to 0.646 (0.7). The trough sits exactly at 0.6. sub_share is the
  reliable, low-noise control for this knob.
- crest_db peaks at Drive 0.625 (11.16 dB), NOT at 0.6 (11.02 dB) or
  0.65 (10.85 dB). So the crest peak is one fine-step (+0.025) ABOVE
  the sub_share trough. THE COARSE SWEEP'S APPARENT CO-LOCATION AT 0.6
  WAS A RESOLUTION ARTIFACT: at 0.025 steps the crest peak (0.625) and
  the sub_share trough (0.6) SEPARATE. The coupling is real but the two
  extrema are offset, not identical.
- crest_db is NOISIER than sub_share (jagged: local dips at 0.425=8.94
  and 0.55=9.75 interrupt the rise). Run-to-run crest variance looks to
  be ~+/-0.5 dB. Treat the crest peak location as 0.60-0.625, not a
  single sharp point; trust sub_share's 0.6 trough as the crisp landmark.
- Map takeaway: to MAXIMIZE crest on this kick, aim Drive ~0.6-0.625.
  To MINIMIZE sub_share (thin the sub, add upper harmonics), aim 0.6.
  They very nearly coincide but the offset means you can't perfectly hit
  both extrema at once. Same caveats as v1 (provisional crest measure;
  Style=0.5; post-mixer tap).
- Rig left UP for follow-ups: Drive restored to ~0.42, STEM_CAP + the
  STEM_KICK_4on4 session clip still in place, Decapitator still the only
  enabled FX. Next moves per the skill: (2) sweep StandardCLIP threshold
  at devices[6] for a cleaner crest control, or (3) swap in the real
  `ears` lab. The clone is disposable under `/Users/anthonybecker/_agent_scratch/`.

SECOND KNOB, A CLEAN CREST LEVER (turn 6): swept the **StandardCLIP**
clipper on the SAME kick (Kick (G) devices[6]). Its `Clipping` param is
the clip threshold in dB, LINEAR: threshold_dB = 144*value - 120 (so the
0.7681 default = -9.40 dB). Single-variable rig: turned Decapitator OFF,
StandardCLIP ON, everything else fixed (Input/Output Gain, Softness 38%,
Clip Type 'Soft Clip Pro'). Swept value 0.6..0.9, 13 steps (threshold
-33.6 dB .. +9.6 dB). `out/snts_kick_clip_thresh_v1/` (spec
`snts_kick_clip_thresh.sweep.json`). Findings:

- threshold -> crest is a CLEAN, MONOTONIC S-CURVE (the opposite of
  Decap Drive's hump). Fully-clipped FLOOR ~4.3 dB for threshold <= -20 dB
  (value <= 0.70); steep MONOTONIC rise through value 0.72..0.83
  (threshold -15..-1 dB): crest 4.55 -> 8.64 dB; then a flat native
  CEILING ~8.7 dB for threshold >= +2 dB (value >= 0.85, kick untouched).
  This IS the cleaner crest control the map wanted: monotonic and
  invertible in the steep region. (The unclipped native kick crest ~8.7
  dB also matches: this is the Decap-OFF raw drum-rack kick.)
- threshold -> sub_share is nearly FLAT (gentle hump 0.716..0.783, peak
  ~value 0.75). So the clipper is almost ORTHOGONAL: it moves crest ~4.4
  dB while sub_share barely moves ~0.06. Contrast Decap, where crest and
  sub_share were tightly coupled. A clean single-axis lever.

WHERE THE ENERGY GOES (full 5-band fingerprint, turn 6): re-assembled
both real-kick sweeps with all canonical band shares (sub/low/mid/high/
air -- measure_local already computes them; just add them to
--measure-keys). These shares are gain-invariant RATIOS, byte-identical
to canonical ears/loudness.py, so they are corpus-comparable NOW.

- DECAP DRIVE @ 0.6 (the sub_share trough): the energy leaving `sub`
  (0.691 -> 0.558) does NOT vanish -- it moves UP into `low` (150-600 Hz:
  0.245 -> 0.329, a +0.084 gain that mirrors sub's -0.133 drop) and `mid`
  (600-4k: 0.060 -> 0.104). So Decap Drive REDISTRIBUTES sub into body/
  low-mid grind. The single sub_share number hid this; it is not a loss,
  it is an upward shift.
- STANDARDCLIP: heavy clipping (value 0.6) roughly TRIPLES `mid_share`
  (0.036 unclipped -> 0.081), ~4x `high`, ~15x `air`. The clip harmonics
  live in mid/high/air, NOT the sub band (sub stays ~flat). So the two
  knobs have DIFFERENT spectral side effects: Decap = sub->low/mid
  redistribution; clipper = added mid/high/air brightness. That is
  exactly the kind of structure the map is meant to name.

MOVE (3) -- REAL `ears` LAB: still NOT runnable on this machine, and it
would add little that is VALID here. The only real `ears` source is an
archived copy (`~/Archives/Archive Desktop projects 2026-04-19/ears/`)
whose `.venv` is broken (its uv-managed CPython 3.12 is gone; deps
librosa/pyloudnorm/soundfile/typer/onnxruntime absent). Standing it up is
a network install, out of scope this turn. IMPORTANT: real ears' extra
metrics (lufs_integrated, true_peak_db) are GAIN-DEPENDENT, so they are
MEANINGLESS on our post-mixer gain-scaled stems -- the whole reason the
tap is valid is gain-invariance. Only band shares (and crest) are valid
on these stems, and measure_local already gives those with canonical
math (real ears sub == our sub_share; real ears has NO crest). So the
measures are already corpus-faithful for what these stems can support.
When ears is restored for FULL-MIX (properly-leveled) audio, the
`--ears-cmd "ears"` swap needs a key shim: ears returns
`loudness.band_energy["sub"]`, not `sub_share`, and no `crest_db`.

See `sweeps/MAP.md` for the assembled knob->measure map (both kick knobs,
with the clipper's invertible target-crest -> threshold lookup).

VALIDATED THE CLIPPER INVERSE TABLE AS A CONTROL (turn 7): first real test
that MAP.md Row-2 is usable as a control, not just a description. Rebuilt the
same single-variable rig on the SNTS clone (still open; STEM_CAP = track 44):
Decapitator devices[1] OFF, StandardCLIP devices[6] ON, all other clipper
params unchanged (Input/Output Gain 0.833, Softness 0.383, Clip Type 'Soft
Clip Pro'). The inverse table predicts crest 5.0/6.0/7.0 dB at Clipping
0.750/0.766/0.782 -- these are evenly spaced (0.016 apart), so ONE 3-step
sweep hits all three. 0.766 and 0.782 are OFF the original 0.025 grid, so a
match tests interpolation AND reproducibility at once. Spec
`snts_kick_clip_validate.sweep.json`, data `out/snts_kick_clip_validate_v1/`.

- SET value 0.750 -> measured crest 5.06 dB (target 5.0, err +0.06).
- SET value 0.766 -> measured crest 5.99 dB (target 6.0, err -0.01).
- SET value 0.782 -> measured crest 7.11 dB (target 7.0, err +0.11).
- ALL within 0.11 dB -- well inside the ~0.3 dB bar and inside the ~0.5 dB
  run-to-run crest noise. sub_share held ~0.774-0.782 (clipper stayed
  orthogonal, as Row 2 says). VERDICT: PASS. The map predicts a knob value
  from a target crest and the kick lands there. First proof the Assistant
  rung can turn a measured crest gap into a specific knob move on this kick.
- Caveat: only tested the steep mid-region (crest 5-7 dB). The floor/ceiling
  saturation rows (4.5, 8.0-8.5 dB) were NOT re-validated this turn; the table
  itself warns those clamp. Same provisional-crest / Style-N.A. / post-mixer
  caveats as the source sweep.
- Rig RESTORED to pre-turn state: Decap ON, StandardCLIP OFF, Clipping back to
  default 0.7681. Clone still open for follow-ups.

THIRD KNOB, kHs TRANSIENT SHAPER / Attack (turn 8, delegated to a subagent):
widened the map off the clipper. Enumerated the VST live (names not in .als):
0 Device On, 1 Attack (default 0.780), 2 Pump, 3 Sustain, 4 Speed, 5 Clip.
Swept Attack (devices[3]) 0..1, 11 steps, single-variable rig (shaper ON,
Decapitator OFF, all else fixed), same STEM_CAP=track44 tap.
`out/snts_kick_transient_attack_v1/`, spec `snts_kick_transient_attack.sweep.json`.

- crest vs Attack is NON-MONOTONIC and BIDIRECTIONAL: a slight dip 9.40->8.77
  dB over 0.0..0.5, then a STEEP clean rise to a PEAK 15.48 dB at 0.9, rolling
  back to 14.08 at 1.0. Span ~6.7 dB -- the LARGEST crest lever of the three
  characterized knobs. Usable/invertible only in the clean Attack 0.5..0.9
  rising region.
- sub_share vs Attack is MONOTONIC DECREASING and large: 0.878 -> 0.360. So
  Attack is STRONGLY COUPLED (crest up = sub down), the opposite of the
  clipper's orthogonality. Energy leaves sub and climbs low/mid/high/air
  (low 0.114->0.365, mid 0.008->0.241): "punch up + brighter click + thinner
  sub", all at once.
- Map placement: three knobs now cover distinct control regimes -- clipper =
  clean orthogonal crest control (Row 2); Attack = biggest crest range but
  sub-coupled (Row 3); Decap Drive = humped voicing knob (Row 1). See MAP.md.
- Rig RESTORED: shaper devices[3] On=0.0, Decap devices[1] On=1.0, Attack back
  to default 0.780. Clone left open, rig up.

MOVE (3) DONE -- the real `ears` lab now RUNS (turn 8, delegated to a subagent).
This REVERSES the prior "not runnable / out of scope" note. Built an isolated
venv at `/Users/anthonybecker/_agent_scratch/ears_lab` (source copied out of the
read-only archive; archive untouched): `uv venv --python 3.12` +
`uv pip install librosa numpy pyloudnorm soundfile typer rich` +
`uv pip install -e . --no-deps`. Network (PyPI) was NOT blocked after all.
`onnxruntime`/essentia/madmom/basic-pitch/demucs intentionally skipped (optional,
degrade gracefully). `requires-python >=3.12` mattered; pinned CPython 3.12.6.

- `.venv/bin/ears analyze <wav> --json --no-embeddings` runs and emits an
  AudioProfile: nested `loudness` with lufs_integrated/short_term/momentary,
  true_peak_db, and `band_energy` (sub/low/mid/high/air).
- CROSS-CHECK (important, confirms our provisional measurer is canonical): on
  bounce_000 of the clip-validate sweep, real ears' `band_energy.sub` =
  0.7821868572 vs measure_local's sub_share = 0.7821868409 -- identical to ~7
  decimals. And running the whole clip-validate sweep through ears+shim gave
  crest 5.059/5.990/7.106 -- byte-identical to measure_local. So measure_local
  IS canonical for the gain-invariant measures; nothing changes numerically by
  switching to ears on these stems.
- THE SHIM (so ears can drop into assemble_curve.py --ears-cmd): real ears has
  NO flat `sub_share` and NO `crest`/`crest_db`. A shim at
  `/Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py` maps
  loudness.band_energy.{sub,low,mid,high,air} -> {sub,low,mid,high,air}_share
  and computes crest = 20*log10(peak/rms) from the wav (same math as
  measure_local). Invoke: `--ears-cmd "/Users/anthonybecker/_agent_scratch/
  ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/
  ears_shim.py" --measure-keys crest sub_share`. Proven end-to-end.
- STILL TRUE: ears' lufs_integrated / true_peak are GAIN-DEPENDENT (the sample
  above read lufs ~-24 LUFS), so they remain MEANINGLESS on our gain-scaled
  post-mixer stems -- the tap is only valid for gain-invariant measures. ears
  becomes NECESSARY (over measure_local) only when we measure FULL-MIX,
  properly-leveled audio, where lufs/true-peak are real. For that day the lab +
  shim are now ready; for the current stems measure_local suffices and matches.

### PHASE 1 COMPLETE -- real `ears` is now the measurer of record

Every sweep with bounced audio was RE-MEASURED with the real `ears` lab and
diffed against `measure_local.py` column by column. Full write-up:
`PHASE1_REPORT.md`. Tool: `compare_measurers.py`.

VERDICT: PASS on all 6 measured sweeps x 6 columns. Tolerance was 1e-6.
Worst single disagreement anywhere = **3.175e-08** (`low_share`,
`snts_kick_transient_attack_v1`) -- 31x inside budget. `crest` matches
**bit-for-bit** (0.000e+00) on every row of every sweep.

Worst per column, across all sweeps:

| crest | sub_share | low_share | mid_share | high_share | air_share |
|---|---|---|---|---|---|
| 0.000e+00 | 2.980e-08 | 3.175e-08 | 1.074e-08 | 1.024e-09 | 1.165e-10 |

ROOT CAUSE of the ~1e-8 residual (investigated, not waved away): input dtype,
not different math. Real `ears` loads audio as float32; `measure_local` casts
to float64 before the FFT. On `snts_kick_clip_validate_v1/bounce_000.wav`,
float64 -> `sub_share` 0.7821868408685838 (== measure_local) and float32 ->
0.782186857204015 (== real ears, exactly). Same band math, different rounding.

Exclusions: `kick_pitch_v1` skipped (known dud, range too narrow, curve flat --
re-sweep before trusting it). `roar_drive_v1` has ZERO wavs (11 param-only OSC
sidecars, `bounce: null`), so it cannot be measured at all -- re-run it through
`run_sweep_stem.py` to get real data. `lufs_*` / `true_peak` remain excluded:
gain-dependent, meaningless on gain-scaled stems, must never enter `MAP.md`.

Guarded going forward by `test_measure_agreement.py`, which fails if the two
measurers ever diverge past 1e-6 on a fixed reference bounce.

### Run-to-run reproducibility of crest (preliminary error bar, n=2)

The Phase-3 `values`-list demo (`out/snts_kick_clip_values_demo_v1/`) happens to
re-bounce two clipper settings that `out/snts_kick_clip_validate_v1/` already
bounced in an earlier session, on a rebuilt rig. That is an independent repeat:

| Clipping | crest, run 1 | crest, run 2 | diff |
|---:|---:|---:|---:|
| 0.750 | 5.0594 dB | 5.0454 dB | 0.014 dB |
| 0.782 | 7.1062 dB | 7.1214 dB | 0.015 dB |

So the whole set -> bounce -> measure chain reproduces crest to ~**0.015 dB**
across sessions. `sub_share` reproduced to ~4e-3 (looser than crest). This is
n=2, NOT the 5-repeat standard deviation Phase 4 step 1 asks for; treat 0.02 dB
as a provisional upper bound and still run the 5-repeat properly. It does
confirm the rig is stable and that `rig.py solo-device` rebuilt the Row-2 rig
faithfully (peak dBFS matched to 0.01 dB too).

### Phase 4 step 1: the real 5-repeat crest noise floor (n=4, one excluded)

Ran `p4_noise.sweep.json`: Clipping fixed at 0.766, bounced 5 times back to
back, same Row-2 rig (`rig.py solo-device --track 6 --device 6`). Data:
`out/p4_noise_v1/`.

Row 0 was a cold-start artifact: `bounce_000.wav` captured **250 s** instead
of the requested ~3.6 s (66 MB vs ~950 KB for rows 1-4). That long near-silent
tail dilutes RMS and inflates crest to 25.96 dB — clearly not real signal
noise. It passed the silent-bounce guard (it is not silent), so the guard did
not catch it. Checked every prior sweep's `bounce_000.wav`: all normal-sized,
so this looks like a one-off tied to the fresh `solo-device` call this
session, not a bug already baked into old data. Logged as an open finding, not
fixed (tooling freeze holds); anyone re-running a noise test should eyeball
row 0's file size before trusting it.

The 4 clean crest values: 5.972, 5.861, 5.888, 5.888 dB.

- mean 5.903 dB, **stdev 0.048 dB**, range 0.111 dB.
- `sub_share` on the same 4 rows: 0.7815-0.7884 (~7e-3 spread), confirming it
  is looser than crest, matching the n=2 provisional finding above.

This is the REAL, CONFIRMED error bar Phase 4 step 1 asked for. It is ~2-3x
the earlier n=2 estimate of 0.02 dB — wider, as the risk note in `PLAN.md`
warned it might be. **Use `--tol 0.05` on `summarize_curve.py` from now on**,
replacing the guessed 10%-of-span default. `MAP.md` updated with this bar.
Every earlier PASS/FAIL verdict that used a tighter implicit bar (e.g. the Row
2 inverse-table validation's 0.3 dB target) still holds, since 0.05 dB is well
inside 0.3 dB — but any future validation using a bar under ~0.05 dB should be
re-checked against this number.

### Live multitrack bounce run: HW002 + SNTS (job `live_multitrack_bounce_v1`)

Bounced every surviving track of two real sets to isolated per-track wav +
`.params.json`, per `research/live-multitrack-bounce.md`. Both clones live
under `/Users/anthonybecker/_agent_scratch/`; originals were never opened.

- **HW002** (`_agent_scratch/HW002/HW002_14.als`): all 12 surviving tracks
  bounced, verified clean. `out/live_multitrack_bounce_v1/hw002/`.
- **SNTS** (`_agent_scratch/SNTS_4-22/SNTS Style track 2026-04-21.als`): 6 of
  7 surviving tracks bounced. Track 8 documented as a legitimate skip (below).
  `out/live_multitrack_bounce_v1/snts-style-track/`.

Total output: 2.4 GB (622 MB SNTS + 1.8 GB HW002). Integrity checker
(`sweeps/check_stems.py`) ran clean on both folders: all wavs have sidecars,
correct/matching durations, no clipping. It does flag multi-second
near-silent stretches on several tracks (HW002 kick/rumble/perc around
120-270s, SNTS kick-g around 169-214s) -- reproduced identically across
independent re-recordings, so these are real arrangement silence (a
breakdown section), not corruption.

**What fought us:**
- A Hammerspoon config was intermittently freezing/crashing Live mid-recording.
  Anthony fixed it; affected tracks (kick/rumble + 5 others in HW002, 1 in
  SNTS) were re-bounced clean afterward.
- The Mac slept/locked once mid-session, freezing Live's transport
  (`is_playing=True` but `current_song_time` frozen, no error surfaced).
  Wrap any future long real-time bounce with `caffeinate -dis`.

**SNTS track 8, "Perc (pitched down)" -- silent in isolation, root-caused, not
a capture bug:**

Every capture attempt (4x real-time arrangement tap across 2 Live relaunches,
plus Live's native offline export/Cmd+Shift+R) returned true digital silence
(~-138 dBFS) despite the track visibly having 10 real, non-muted arrangement
clips spanning beats 0-1024. Ruled out solo-elsewhere, session/arrangement
view state, per-clip mute, and freeze -- none applied.

Root cause: `song.tracks[8].has_midi_input=True, has_audio_input=False` -- this
is a MIDI track. Its 6 devices (SSL FlexVerb, Shifter, HPF/Eq8, Utility, NTPD
Lite, Utility) all report `device.type == 2` (audio_effect). Zero devices are
`type == 1` (instrument). A MIDI track with no instrument cannot produce
audio no matter how it's captured -- the notes are real, but nothing turns
them into sound.

Confirmed this was a real, dated change, not an always-broken track:
decompressed (read-only, gzip) 25 auto-saved `.als` revisions in the
project's `Backup/` folder and diffed each one's device list for this track.
A native `DrumGroupDevice` (Drum Rack, browser path `X-Synths#Drum Rack`)
sits at the front of the chain in every backup through `2026-04-06 232256`,
and is gone from every save from `2026-04-06 234103` onward, including the
current working file. The other 6 devices (same device IDs) are untouched
across that boundary -- a clean, single-device deletion in an ~18-minute
window, not a broader edit. This means the instrument has been missing in
Anthony's real, current mix too, for about 2 weeks -- not just in this
isolated bounce.

Decision (confirmed with Anthony 2026-09-11): documented as a legitimate
skip, no wav produced. Record:
`out/live_multitrack_bounce_v1/snts-style-track/08__perc-pitched-down.SKIPPED.json`.

General lessons from this pulled into `ableton-guide`/`ableton-live-control`
skills (see their "Diagnosing silent tracks" section) rather than repeated
here: check track type + `device.type` before assuming a capture bug, and
diff saved revisions/backups to date a missing device instead of guessing.

## 5. Where things live

- Sweep code: `autodaw/hands/sweeps/` (this folder).
- `hands` package: `autodaw/hands/` (config -> Live pipeline).
- Ableton skill: `~/.agents/skills/ableton-live-control/`.
- Virtual-display skill: `~/.agents/skills/virtual-display/`.

## 6. The seam (the file contract — keep it stable)

- IN: a `*.sweep.json` spec. Which knob, what range, how many steps.
- OUT, per setting: `bounce_NNN.wav` + `bounce_NNN.params.json`.
  The sidecar holds the requested value AND the read-back true value,
  the device path, unit, tempo, predicted measure. A wav without its
  sidecar is a dead row.
- The lab reads the pairs later and fills `measure`. Measurement is
  out-of-band on purpose. Do not couple the two sides in code.

## 7. How to drive Live

Path A (OSC), always safe, no bridge:
```bash
cd ~/.agents/skills/ableton-live-control
python3 scripts/live.py /live/song/get/track_names
python3 scripts/live.py /live/device/set/parameter/value 1 1 1 0.6
```

Path B (LOM/MCP on TCP 16619), powerful, crash-prone:
```bash
python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py "song.tempo"
```
It is ENABLED now: `AbletonLiveMCP` is Control Surface row 3
(In/Out: None). Row 1 = MiniLab 3 hardware. Row 2 = AbletonOSC.
The choice persists across restarts. Check with `nc -z 127.0.0.1 16619`.

Path B crash rules (non-negotiable, from the skill's lom-guide):
- Never read a param in the same call you wrote it. Write, then read.
- One device, <= 20 params per call. No giant sweeps in one call.
- Sleep ~0.3s between browser loads. One VST load per call.
- Stay under 12s per call. Keep sleeps <= 0.5s.
- After track create/delete, re-fetch `song.tracks[i]` (alias goes stale).

## 8. Current machine state (verify before you act)

- Live runs an UNSAVED "Untitled" set with TWO tracks we built:
  - track 0 `1-ref_kick`: empty audio, doubles as the stem recorder.
  - track 1 `3-Kick`: Drum Rack -> pad 36 -> Simpler "Kick 49 Hz",
    plus a 4-on-4 MIDI clip in session slot 0.
- Swept knob = Simpler `Transpose`:
  `song.tracks[1].devices[0].drum_pads[36].chains[0].devices[0]`.
- The set is NOT saved. If Live closes, the instrument is gone.
  It rebuilds in seconds (next section).
- NOTE: Live has been closed between turns before, losing the set.
  Do not assume it is up. Check `pgrep -f "Ableton Live"` and OSC first.

## 9. Rebuild the plugin set (if it is gone)

```bash
cd autodaw/hands
uv run hands execute --config sweeps/base_kick.json
```
`base_kick` deletes tracks down to one, then builds. If the open set
has GROUP tracks, `delete_track` can fail. Reduce to one track first
via Path B, then run the build. `base_kick.py` uses `Kick 49 Hz.wav`,
a sample that exists on this machine.

## 10. Run a sweep (Path B, the reliable route)

```bash
cd autodaw/hands
uv run python sweeps/run_sweep_stem.py --sweep sweeps/kick_pitch_wide.sweep.json
```
It sets the knob, reads the true value, bounces an ISOLATED stem, and
writes the sidecar. It is resumable (skips rows that already have a
wav + sidecar). `--no-restore` leaves the last value set.

It also now supports an explicit `values` list in the spec (used verbatim
instead of start/stop/steps; duplicates allowed, for repeat-bounce noise
tests) and it FAILS FAST on a silent/tiny bounce rather than writing a dead
row. See section 12.5.

Then measure + assemble the curve. **ears is the measurer of record:**
```bash
uv run python sweeps/assemble_curve.py \
  --dir sweeps/out/<sweep_id> \
  --ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py" \
  --measure-keys crest sub_share low_share mid_share high_share air_share \
  --out sweeps/out/<sweep_id>/<sweep_id>.acceptance.ears.csv
```
Then auto-summarize instead of hand-reading the curve:
```bash
uv run python sweeps/summarize_curve.py \
  --csv sweeps/out/<sweep_id>/<sweep_id>.acceptance.ears.csv
```
READING GOTCHA: do NOT `column -t` an acceptance CSV. VST params have a blank
`value_string`, which shifts the columns and silently misreads the data. The
CSV is now fully quoted, and `assemble_curve.py` writes a pre-aligned
`<sweep_id>.acceptance.txt` next to it -- read that by eye.

## 11. The runners (which, and why)

- `run_sweep_stem.py` — USE THIS. Taps the source track's output into
  the existing audio track 0, plays the SESSION clip, arrangement-
  records the stem. Reliable here. Isolated stem = better for measuring.
- `run_sweep.py` — older, uses `hands.recorder` resampling. Flaky here;
  it bounced silence. Two causes, one fixed:
  1. Session-clip override left the arrangement silent. FIXED in
     `hands/src/hands/recorder.py` (`song.back_to_arranger = 0`).
  2. Resampling tap on fresh audio tracks stays silent after heavy
     track churn. Not fully fixed. Restart Live to clear it if needed.
- `run_sweep_osc.py` — Path-A runner. Set + read back over OSC. Only
  top-level params. Optional `--bounce` uses the osascript export
  (unique filenames only; run Live off-screen on a virtual display).

## 12. The measurer (ears is the record; measure_local is the fallback)

**Measurer of record = the real `ears` lab.** There are TWO shims that reach it
and both return byte-identical real-ears band shares. Prefer the FIRST.

### 12a. PREFERRED: the in-repo shim + `EARS_CMD` (durable)

```bash
export EARS_CMD="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/ears"
uv run python sweeps/assemble_curve.py --dir sweeps/out/<sweep_id> \
  --ears-cmd "uv run python sweeps/ears_shim.py" \
  --measure-keys crest_db sub_share low_share mid_share high_share air_share \
  --out sweeps/out/<sweep_id>/<sweep_id>.acceptance.ears.csv
```

Why this one: `sweeps/ears_shim.py` lives IN THE REPO, so it survives
`_agent_scratch` being wiped. When `$EARS_CMD` resolves it uses real ears'
`loudness.band_energy` for the shares; when it does NOT resolve it silently
falls back to `measure_local`'s band math, which Phase 1 proved agrees to
3.2e-8. So the pipeline never breaks, it only loses corpus exactness. It also
parks ears' gain-dependent metrics under an `ears_extra` key carrying an
explicit `_warning`, so they cannot be mistaken for valid.

Verified: `measurer: "ears_shim (real ears band shares + local crest_db)"`,
`sub_share = 0.782186857204015` (exactly real ears, not the float64 value).

Note it emits **`crest_db`**, so use `crest_db` in `--measure-keys`.

### 12b. Equivalent: the lab-side shim (emits `crest`)

```
--ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py"
--measure-keys crest sub_share low_share mid_share high_share air_share
```

This is what produced the existing `*.acceptance.ears.csv` files, which is why
their crest column is named `crest`. Same numbers; but it dies with
`_agent_scratch`.

### 12c. Fallback: `measure_local.py` (offline, no lab at all)

```
--ears-cmd "uv run python sweeps/measure_local.py"
--measure-keys crest_db sub_share low_share mid_share high_share air_share
```

Its 5-band math is copied VERBATIM from canonical `ears/loudness.py`. Agrees
with real ears to better than 3.2e-8 on every measured sweep (section 4).
`test_measure_agreement.py` keeps them honest.

### 12d. The raw lab

`/Users/anthonybecker/_agent_scratch/ears_lab/` with a working `.venv`, a
`pyproject.toml`, and a `uv.lock` (220 KB — that lock IS the version pin, copy
it somewhere durable). Raw CLI:
`.venv/bin/ears analyze <wav> --json --no-embeddings`. Real `ears` emits NESTED
`loudness.band_energy.<band>` and has NO crest at all, which is exactly why a
shim is required — bare `--ears-cmd "ears"` CANNOT feed this pipeline.

### 12e. The rule about gain

NEVER use `lufs_*` or `true_peak` on these stems. They are gain-dependent and
our taps are gain-scaled, so the numbers are meaningless. Only the five band
shares and crest are valid here. They become real only on full-mix,
properly-leveled audio.

## 12.5 The rig helper (`rig.py`)

Stop toggling devices by hand. `rig.py` snapshots, solos, and restores device
state on a track, and VERIFIES every restore by read-back.

```bash
uv run python sweeps/rig.py snapshot --track 6 --name snts_kick_devices
uv run python sweeps/rig.py solo-device --track 6 --device 6 --name my_rig
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

`snapshot` is read-only. `solo-device` sets the target device On=1 and every
other device On=0 (it keeps the track's instrument ON so the rig cannot bounce
silence), and writes a `.pre.json` restore point BEFORE any write. `restore`
refuses to run if the track name or device count drifted, then prints a
pass/fail table and exits nonzero on any mismatch.

`sweeps/snapshots/snts_kick_devices.json` is the ORIGINAL-state restore target
for track 6. Restore to it after every experiment.

## 13. Files in this folder

- `base_kick.py` / `base_kick.json` — Path-B build config.
- `run_sweep_stem.py` — the reliable Path-B sweep runner. USE THIS.
- `run_sweep.py` — older resampling runner (flaky here).
- `run_sweep_osc.py` — Path-A runner (+ optional osascript bounce).
- `kick_pitch_wide.sweep.json` — corrected pitch spec (0..+36 st).
- `kick_pitch.sweep.json` — first pitch spec (-10..+10; saturated).
- `roar_drive.sweep.json` — Path-A drive spec (from the old real set).
- `measure_local.py` — OFFLINE FALLBACK measurer (canonical sub_share).
- `assemble_curve.py` — joins sidecars (+ measurer) into a verdict CSV,
  plus a pre-aligned `.txt` view that cannot column-shift.
- `summarize_curve.py` — auto-reads an acceptance CSV: direction,
  extrema + where, span, and the invertible region(s).
- `compare_measurers.py` — max abs diff per column between two
  acceptance CSVs (folds `crest_db` into `crest`).
- `test_measure_agreement.py` — regression test: fails if ears and
  `measure_local` diverge past 1e-6 on a fixed reference bounce.
- `rig.py` — device snapshot / solo-device / verified restore.
- `snapshots/snts_kick_devices.json` — track 6 original-state restore
  target.
- `PHASE1_REPORT.md` — the ears-vs-local validation write-up.
- `PLAN.md` — the five-phase tidy-first work plan. Read it first.
- `STATUS.md` — which phases are done, which are not.
- `snts_kick_clip_values_demo.sweep.json` — demo of the explicit
  `values` list; doubles as an n=2 reproducibility check.
- `snts_kick_decap_drive.sweep.json` / `out/snts_kick_decap_drive_v1/`
  — first real-instrument sweep (Decap Drive 0..1, 11 steps).
- `snts_kick_decap_drive_fine.sweep.json` /
  `out/snts_kick_decap_drive_fine_v2/` — finer 0.4..0.7, 13 steps,
  resolving the 0.6 hump (turn 6).
- `out/kick_pitch_wide_v1/` — 13 bounces + MEASURED acceptance curve.
- `out/kick_pitch_v1/` — first 11 bounces (sub_share saturated).
- `out/roar_drive_v1/` — earlier OSC sweep on Anthony's old set.

## 14. DO THIS NEXT (in order)

### Action A — add `drive -> crest` (do first; autonomous, ~10 min)
Adds the second predicted mapping and exercises Path B device loading.
1. Load a distortion on the kick track (track 1) over Path B:
   ```python
   # live_mcp.py, then re-query in a SEPARATE call
   load_to(song.tracks[1], browser.audio_effects, "Roar")
   time.sleep(0.3); result = [d.name for d in song.tracks[1].devices]
   ```
   (Roar's drive param is `Drive`. Saturator also has `Drive`.)
2. Write `drive_crest.sweep.json`: `device_expr` = the new device
   (e.g. `song.tracks[1].devices[1]`), `param_name` = "Drive",
   range 0..1, ~11 steps, `predicted_measure` = "crest",
   `predicted_direction` = "increasing" (more drive squashes peaks;
   confirm the sign empirically), `output_dir` = out/drive_crest_v1.
3. Run `run_sweep_stem.py` on it, then `assemble_curve.py` with
   `--measure-keys crest_db sub_share`. Log the verdict.

### Action B — get onto Anthony's REAL instruments (the real payoff)
The 49 Hz Simpler is a synthetic proof. The map only helps production
when built on his actual racks (kick group: Roar / Decapitator /
clipper; pitched hats; freeze-resample pads). This needs Anthony to
open/save one of his real sets. It is a dependency on him — ask for it.
Then retarget `device_expr` at the real device and sweep.

### Action C — get the real `ears`
Swap `measure_local` for the real lab so measures are corpus-
comparable and the Critic's "gap vs corpus" is well-defined. Then the
Assistant can turn a measured gap into a specific knob move via the map.

## 15. Safety rules (do not skip)

- The set is UNSAVED. Treat it as fragile. Do not restart Live unless
  you have saved, or you accept losing the built instrument.
- Always restore any param you change. The runners already do; keep it.
- osascript export only OFF-SCREEN (virtual display), always a UNIQUE
  filename (the "replace existing?" sheet wedges the exporter).
- Always move Live back on-screen BEFORE destroying a virtual display.
- Prefer OSC/text over screenshots. Retina vdisplay shots are ~15 MB;
  crop/downscale before reading one.
