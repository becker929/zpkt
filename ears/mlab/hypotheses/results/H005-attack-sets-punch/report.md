# H005 — At matched loudness, a slow-attack bus compressor keeps more punch than a fast one

Run 2026-09-26 00:58 · chapter 5-7 · source: compression chapters (attack/release, punch, microdynamics)

**Claim.** With the same threshold and ratio, 30 ms attack lets each kick's front edge through before gain reduction lands; 0.1 ms attack clamps it. A 3 ms variant is included because the calibration kick loop peaked in punch at 1-5 ms, not 30 ms. So transient contrast and block crest should be higher with slow attack, even after loudness matching.

**Verdict: NOT SUPPORTED**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| dynamics.transient_contrast_median_db | slowA − fastA | > | 0.5 | 0.16 | FAIL |
| | *slow attack preserves the hit* | | | | |
| dynamics.block_crest_median_db | slowA − fastA | > | 0.5 | 0.5 | INCONCLUSIVE |
| | *microdynamics survive slow attack* | | | | |

## Measurements

| metric | as_is | fastA | midA | slowA |
|---|---|---|---|---|
| loudness.integrated | -13.84 | -13.84 | -13.84 | -13.84 |
| loudness.true_peak | -0.48 | -4.32 | -1.94 | -1.49 |
| loudness.plr | 13.36 | 9.52 | 11.9 | 12.35 |
| dynamics.crest_db | 14.82 | 10.88 | 13.18 | 13.11 |
| dynamics.block_crest_median_db | 8.6 | 8.13 | 8.46 | 8.63 |
| dynamics.transient_contrast_median_db | 8.12 | 7.67 | 7.74 | 7.83 |
| loudness.lra | 2.08 | 1.26 | 1.23 | 1.13 |

## Variants

- **as_is**: demo → 
- **fastA**: demo → compressor → normalize_lufs
- **midA**: demo → compressor → normalize_lufs
- **slowA**: demo → compressor → normalize_lufs

## Listening

Blind ABX kit in `hypotheses/results/H005-attack-sets-punch/abx` (level-matched). Score with `python3 -m mlab abx-score <folder> <answers>`.

## Interpretation

The Python compressor is a reference design, not Glue Compressor. To test Live's device, render both settings in Live, drop them in audio/inbox/, and use 'file:' variants. Measure the device's real attack first with 'mlab probe' + 'mlab comp-probe'.

