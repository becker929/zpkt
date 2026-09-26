# H003 — A 15 Hz high-pass removes HW002's DC offset and frees peak headroom without changing loudness

Run 2026-09-25 23:17 · chapter 14 · source: signal flow and premaster chapter; findings L-007 and L-011 in LEARNINGS.md

**Claim.** The demo carries a steady offset near -35 dBFS while the kick section plays (asymmetric distortion). Removing it with a 15 Hz high-pass should lower the sample peak by at least 0.2 dB and leave integrated loudness within 0.1 LU.

**Verdict: NOT SUPPORTED**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| word_length.dc_max_dbfs | hp15 − 0 | < | -60 | -107.5 | PASS |
| | *offset gone* | | | | |
| loudness.sample_peak | hp15 − as_is | < | -0.2 | 0.1 | FAIL |
| | *headroom freed* | | | | |
| loudness.integrated | hp15 − as_is | abs< | 0.1 | -0.01 | PASS |
| | *loudness unchanged* | | | | |
| tonal.group.sub | hp15 − as_is | abs< | 0.2 | -0.03 | PASS |
| | *15 Hz leaves the kick's sub alone* | | | | |

## Measurements

| metric | as_is | hp15 | hp30 |
|---|---|---|---|
| word_length.dc_max_dbfs | -37.68 | -107.5 | -104.91 |
| loudness.sample_peak | -0.48 | -0.38 | -0.45 |
| loudness.true_peak | -0.48 | -0.37 | -0.45 |
| loudness.integrated | -13.84 | -13.85 | -13.92 |
| loudness.plr | 13.36 | 13.47 | 13.47 |
| tonal.group.sub | -7.42 | -7.45 | -7.75 |
| tonal.group.bass | -2.67 | -2.67 | -2.61 |

## Variants

- **as_is**: demo → 
- **hp15**: demo → eq
- **hp30**: demo → eq

## Interpretation

If supported, put a DC/infrasonic high-pass first in the mastering chain (EQ Eight low cut, 48 dB/oct, at ~10-15 Hz), and look for the device that makes the offset.

