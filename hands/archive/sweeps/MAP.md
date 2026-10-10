# The knob -> measure map (assembled)

This is the Assistant's lookup: which knob moves which measure, by how much,
where it stops being monotonic, and (for clean knobs) how to invert it -- pick a
target measure and read off the knob value. Built from measured sweeps in
`out/`. All measures here are GAIN-INVARIANT (band-energy shares are ratios;
crest is peak/RMS), so they are valid on the post-mixer stem taps and are
byte-identical to canonical `ears` band math. LUFS / true-peak are NOT listed:
they are gain-dependent and meaningless on gain-scaled stems.

Notation: `crest` = crest_db (peak/RMS, dB; higher = punchier/less squashed).
`sub_share` = fraction of 20-20k energy in the 20-150 Hz sub band. Band shares
sum to 1 across sub/low/mid/high/air.

## Measurer of record and error bars

All numbers below are now confirmed against the **real `ears` lab** (Phase 1;
see `PHASE1_REPORT.md`). Every sweep was re-measured with ears and diffed
against the provisional `measure_local.py`: worst disagreement anywhere was
3.2e-08 against a 1e-6 budget, and `crest` matched bit-for-bit. So the earlier
curves stand as written -- ears did not change any conclusion.

Measurer command (use for every new row — the in-repo shim, so it survives
`_agent_scratch` being wiped; see `HANDOFF.md` §12):

```bash
export EARS_CMD="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/ears"
--ears-cmd "uv run python sweeps/ears_shim.py"
--measure-keys crest_db sub_share low_share mid_share high_share air_share
```

(The existing `*.acceptance.ears.csv` files name that column `crest` rather than
`crest_db` because they were built with the lab-side shim. Same quantity.)

**Error bar on crest: 0.048 dB stdev, 0.111 dB range (CONFIRMED, n=4).**
Phase 4 step 1: Clipping fixed at 0.766, bounced 5 times back to back
(`out/p4_noise_v1/`). Row 0 of that run was a cold-start artifact (see below)
and is excluded; the remaining 4 crest values were 5.972, 5.861, 5.888, 5.888
dB. This is ~2-3x the earlier n=2 provisional bar of 0.02 dB, so treat **0.05
dB** as the working crest noise floor and pass `--tol 0.05` to
`summarize_curve.py` from now on. `sub_share` on the same 4 rows held to
0.7815-0.7884 (~7e-3 spread), confirming it is looser than crest as expected.
This bar covers the RENDER chain only; it does not cover a hump's location on
a coarse grid, where the grid spacing dominates (see Phase 4 step 6).

**Finding: first bounce after a fresh `rig.py solo-device` call can be way
too long.** Row 0 of `p4_noise_v1` captured 250 s of audio instead of the
requested ~3.6 s (66 MB vs ~950 KB for rows 1-4), diluting RMS with a long
near-silent tail and inflating crest to 25.96 dB. It passed the silent-bounce
guard (it is not silent), so the guard alone will not catch it. Checked all
prior sweeps' bounce_000 files: every one is normal-sized, so this looks like
a one-off cold-start artifact tied to this session, not a standing bug in
prior data. Until root-caused, treat the FIRST bounce right after a
`solo-device` call as suspect: eyeball its file size against the rest before
trusting row 0 of any new sweep.

---

## Target: SNTS Style track (clone) / Kick (G) = track 6

A standalone Drum-Rack MIDI kick. Three crest-affecting knobs characterized.

### Row 1 -- Decapitator (devices[1]) / Drive   [Style fixed 0.5, AutoGain off]

| aspect | finding |
|---|---|
| crest vs Drive | NON-MONOTONIC. Hump: local max ~11.1 dB at Drive **0.60-0.625**, falls to ~8.1 dB at 1.0 and ~9.1 dB at 0.4. Noisy (+/-0.5 dB). |
| sub_share vs Drive | U-shaped. MINIMUM **0.558 at Drive 0.6**, ~0.75 at the ends. Clean, low-noise. |
| spectral side effect | At Drive 0.6 the sub energy REDISTRIBUTES up: `low` (150-600) rises 0.245->0.329, `mid` 0.060->0.104. Not a loss -- an upward shift into body/grind. |
| usable as a control? | POORLY for crest (non-monotonic, can't invert). OK as a "sub-thinning / add low-mid grind" knob, strongest at ~0.6. |
| data | `out/snts_kick_decap_drive_v1/` (0..1, 11 steps), `out/snts_kick_decap_drive_fine_v2/` (0.4..0.7, 13 steps). |

### Row 2 -- StandardCLIP (devices[6]) / Clipping = threshold   [clipper only]

Threshold is LINEAR in the param: **threshold_dB = 144 * value - 120**
(value 0.7681 = -9.40 dB default). Softness 38%, Clip Type "Soft Clip Pro".

| aspect | finding |
|---|---|
| crest vs threshold | CLEAN MONOTONIC S-curve. Floor ~4.3 dB (thr <= -20 dB), steep rise thr -15..-1 dB, ceiling ~8.7 dB (thr >= +2 dB, native unclipped). |
| sub_share vs threshold | ~FLAT (gentle hump 0.72-0.78). Nearly ORTHOGONAL to crest. |
| spectral side effect | Harder clipping adds UPPER harmonics: `mid` share ~triples (0.036->0.081), `high` ~4x, `air` ~15x. Sub stays put. So this knob = "crest down + brightness up", low end untouched. |
| usable as a control? | YES -- the clean crest lever. Monotonic + invertible in the steep region, and it barely disturbs the sub. Prefer this over Decap Drive for crest moves. |
| data | `out/snts_kick_clip_thresh_v1/` (value 0.6..0.9, 13 steps). |

#### Inverse lookup (Row 2): target crest -> knob   [VALIDATED as a control]

VALIDATED (turn 7): set the predicted values 0.750/0.766/0.782 (targets
5.0/6.0/7.0 dB), bounced, measured crest 5.06/5.99/7.11 dB -- all within
0.11 dB of target (bar was 0.3 dB). 0.766 and 0.782 were off the original
grid, so this tested interpolation + reproducibility. sub_share held ~0.78
(stayed orthogonal). Data: `out/snts_kick_clip_validate_v1/`. Only the steep
mid-region (5-7 dB) was re-checked; the saturating floor/ceiling rows below
still clamp and were not re-validated.

Valid only inside the steep region, crest ~4.5..8.6 dB. Below the floor
(~4.3 dB) or above the ceiling (~8.7 dB) this knob saturates -- it cannot push
crest past those limits. Linear-interpolated from the measured curve:

| target crest (dB) | Clipping value | threshold (dB) |
|---:|---:|---:|
| 4.5 | 0.724 | -15.7 |
| 5.0 | 0.750 | -12.0 |
| 5.5 | 0.758 | -10.9 |
| 6.0 | 0.766 |  -9.8 |
| 6.5 | 0.773 |  -8.6 |
| 7.0 | 0.782 |  -7.4 |
| 7.5 | 0.791 |  -6.1 |
| 8.0 | 0.800 |  -4.9 |
| 8.5 | 0.819 |  -2.0 |

Apply over Path B: `song.tracks[6].devices[6].parameters[6].value = <value>`
(after enabling the device, `parameters[0].value = 1.0`). Or by threshold dB:
`value = (threshold_dB + 120) / 144`.

### Row 3 -- kHs Transient Shaper (devices[3]) / Attack   [shaper only]

VST params (enumerated live): 0 Device On, 1 **Attack** (default 0.780), 2 Pump,
3 Sustain, 4 Speed, 5 Clip. Attack is the transient-gain lever. Single-variable
rig: shaper ON, Decapitator OFF, everything else fixed. Swept Attack 0..1, 11
steps. `out/snts_kick_transient_attack_v1/`.

| aspect | finding |
|---|---|
| crest vs Attack | NON-MONOTONIC, bidirectional. Slight DIP 9.40->8.77 dB over 0.0..0.5, then a STEEP clean rise to a PEAK 15.48 dB at 0.9, rolling back to 14.08 at 1.0. Span ~6.7 dB -- the LARGEST crest lever of the three knobs. |
| sub_share vs Attack | MONOTONIC DECREASING, big move: 0.878 (Attack 0) -> 0.360 (Attack 1). Boosting the transient pulls energy out of the sub. Strongly COUPLED to crest (unlike the clipper). |
| spectral side effect | Energy leaving `sub` climbs into low/mid/high/air as Attack rises: low 0.114->0.365, mid 0.008->0.241. Attack = "punch up + click brighter + sub thinner", all at once. |
| usable as a control? | As a crest lever, YES but only in the clean monotonic-rising region Attack **0.5..0.9** (crest 8.8->15.5 dB, invertible there). NOT invertible below 0.5 (flat/dip) or at the 1.0 reversal. Every crest move here drags sub_share DOWN, so it is NOT orthogonal -- prefer the clipper (Row 2) when you must keep the sub put. |
| data | `out/snts_kick_transient_attack_v1/` (Attack 0..1, 11 steps), spec `snts_kick_transient_attack.sweep.json`. |

Contrast across the three knobs: **clipper (Row 2)** = clean monotonic crest,
orthogonal to sub (best pure crest control). **Transient Attack (Row 3)** =
biggest crest range but sub-coupled (use when you WANT punch + a thinner sub).
**Decap Drive (Row 1)** = humped, hard to invert (a grind/sub-thinning voicing
knob, not a crest control).

---

## Earlier synthetic reference (plugin kick, not a real instrument)

- Simpler "Kick 49 Hz" / Transpose: `sub_share` MONOTONIC DECREASING with pitch
  (cliff at +18->+21 st where the fundamental crosses the 150 Hz band edge);
  `crest` MONOTONIC INCREASING. Data in `out/kick_pitch_wide_v1/`. This is a
  documented REVERSAL vs the research register (register predicted sub_share
  increasing). See HANDOFF section 4.

---

## How to read / extend this map

- Sweep the WHOLE range: real distortion/pitch knobs are often non-monotonic
  (Row 1). Endpoints alone hide humps.
- Pick a range that CROSSES the band edge you measure, or a share saturates flat
  and "flat" is mistaken for "no effect".
- Prefer knobs that are monotonic AND spectrally orthogonal for control (Row 2):
  they let the Assistant hit a target measure without smearing others.
- Add a row: `rig.py solo-device` to isolate the device, `run_sweep_stem.py` to
  sweep + bounce, `assemble_curve.py` with the ears `--ears-cmd` above, then
  `summarize_curve.py` to read off direction / extrema / invertible region.
  Finish with `rig.py restore`. Record monotonicity, range, spectral side
  effect, and (if clean) the inverse lookup here.
- Never `column -t` an acceptance CSV: VST params leave `value_string` blank and
  the columns shift. Read the `*.acceptance.txt` aligned view instead.
- Never put `lufs_*` or `true_peak` in this file. They are gain-dependent and
  our stem taps are gain-scaled, so those numbers mean nothing here.
