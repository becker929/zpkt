# The knob -> measure map (real instruments)

Rows measured by driving Ableton Live headlessly on Anthony's machine: open a
copy-on-write clone of a real set, set one device parameter, bounce an isolated
stem of the instrument, measure it, assemble `{param -> measure}`. Originals are
never saved over. This file is the research record of that map; the running lab
log lives with the rig.

Measures here are GAIN-INVARIANT (band shares are ratios, crest is peak over
RMS), which is what makes a post-fader tap valid. Band-share maths is copied
verbatim from canonical `ears/loudness.py`, so shares are comparable with the
corpus numbers in parts two to four. LUFS and true peak are deliberately absent:
the taps are gain-scaled and those metrics would be meaningless on them.

Notation: `crest` = crest_db (peak/RMS, dB; higher = punchier).
`sub_share` = fraction of 20 Hz-20 kHz energy in the 20-150 Hz band. Shares over
sub/low/mid/high/air sum to 1.

---

## Target: SNTS Style track (clone), Kick (G), track 6

A standalone Drum-Rack MIDI kick. Two knobs characterised so far.

### Row 1. Decapitator (devices[1]) / Drive   [Style fixed 0.5, AutoGain off]

| aspect | finding |
|---|---|
| crest vs Drive | NON-MONOTONIC. 9.82 dB at 0.0, local max ~11.1 dB at 0.60-0.625, 8.14 dB at 1.0. Noisy, about +/-0.5 dB run to run. |
| sub_share vs Drive | U-shaped and low-noise. Minimum **0.558 at Drive 0.6**, ~0.75 at both ends. |
| spectral side effect | At 0.6 the sub energy redistributes UP: low (150-600 Hz) 0.245 -> 0.329, mid 0.060 -> 0.104. Not a loss, an upward shift into body. |
| usable as a control? | Poorly for crest (cannot invert). Fine as a "thin the sub, add low-mid" knob, strongest near 0.6. |
| runs | coarse 0..1 in 11 steps; fine 0.4..0.7 in 13 steps (0.025). |

### Row 2. StandardCLIP (devices[6]) / Clipping = threshold   [clipper only]

Threshold is linear in the parameter: **threshold_dB = 144 * value - 120**
(the 0.7681 default is -9.40 dB). Softness 38%, Clip Type "Soft Clip Pro".

| aspect | finding |
|---|---|
| crest vs threshold | CLEAN MONOTONIC S-curve. Floor ~4.3 dB (threshold <= -20 dB), steep rise -15..-1 dB, ceiling ~8.7 dB (native, unclipped). |
| sub_share vs threshold | Near-flat (gentle hump 0.716-0.783). Nearly orthogonal to crest. |
| spectral side effect | Clip harmonics land in mid (~3x), high (~4x) and air (~15x). Sub stays put. |
| usable as a control? | YES. The clean crest lever: monotonic, invertible in the steep region, and it barely disturbs the low end. Prefer it over Decap Drive for crest moves. |
| runs | value 0.6..0.9 in 13 steps. |

#### Inverse lookup: target crest -> knob

Valid only inside the steep region, crest ~4.5-8.6 dB. Outside it the knob
saturates and cannot push crest past the floor or ceiling.

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

By threshold: `value = (threshold_dB + 120) / 144`.

---

## Earlier synthetic reference (plugin kick, not a real instrument)

Simpler "Kick 49 Hz", swept Transpose 0..+36 st: `sub_share` monotonic
DECREASING (0.9996 -> 0.0023), with a cliff at +18 -> +21 st where the
fundamental crosses the 150 Hz band edge; `crest` monotonic INCREASING
(5.23 -> 13.83 dB). Treat as a documented reversal of the naive expectation
that raising a kick's pitch raises its sub share: for a sampled kick it lowers
it, because the fundamental leaves the sub band.

## Method lessons (they generalise, the numbers do not)

- Sweep the WHOLE range. Real distortion knobs are not monotonic, and the two
  endpoints alone hid the Drive hump completely.
- Choose step size deliberately. At 0.1 the crest peak and sub trough looked
  co-located at 0.6; at 0.025 they separate (0.625 and 0.6).
- Pick a range that CROSSES the band edge you measure, or the share saturates
  flat and "flat" gets mistaken for "no effect".
- Prefer knobs that are monotonic AND spectrally orthogonal for control: they
  let a target measure be hit without smearing the others.

## Limits

One kick, in one set, with Decapitator Style fixed at 0.5. Another style moves
the curve. Nothing here is a claim about drive knobs in general; the point is
that each knob has to be measured.
