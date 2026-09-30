# H001 — Limiting HW002 louder than -14 LUFS gains nothing on YouTube and costs peak-to-loudness ratio

Run 2026-09-26 00:56 · chapter 17-19 · source: loudness war chapters; platform behaviour is observed, not documented (tier 4-6)

**Claim.** If YouTube turns loud uploads down to about -14 LUFS, a -9 LUFS master of HW002 plays at the same loudness as the current -13.8 LUFS demo, but with less peak-to-loudness ratio (PLR), i.e. flatter hits.

**Verdict: INCONCLUSIVE**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| loudness.integrated | loud_-9@youtube − as_is@youtube | abs< | 0.3 | 0.0 | PASS |
| | *after normalisation both play at about -14 LUFS* | | | | |
| loudness.plr | loud_-9 − as_is | < | -3 | -5.36 | PASS |
| | *the extra loudness is paid for with at least 3 dB of PLR* | | | | |
| dynamics.transient_contrast_median_db | loud_-9 − as_is | < | 0 | 0.0 | INCONCLUSIVE |
| | *hits stand less far above the body* | | | | |

## Measurements

| metric | as_is | loud_-9 | as_is@youtube | loud_-9@youtube |
|---|---|---|---|---|
| loudness.integrated | -13.84 | -9.0 | -14.0 | -14.0 |
| loudness.true_peak | -0.48 | -1.0 | -0.64 | -6.0 |
| loudness.plr | 13.36 | 8.0 | 13.36 | 8.0 |
| loudness.psr_min | 7.13 | 7.13 | 7.13 | 7.13 |
| loudness.lra | 2.08 | 1.24 | 2.08 | 1.24 |
| dynamics.crest_db | 14.82 | 9.35 | 14.82 | 9.35 |
| dynamics.block_crest_median_db | 8.6 | 8.57 | 8.6 | 8.57 |
| dynamics.transient_contrast_median_db | 8.12 | 8.12 | 8.12 | 8.12 |

## Variants

- **as_is**: demo → 
- **loud_-9**: demo → master_to
- **as_is@youtube**: as_is → platform
- **loud_-9@youtube**: loud_-9 → platform

## Listening

Blind ABX kit in `hypotheses/results/H001-loudness-buys-nothing-on-youtube/abx` (level-matched). Score with `python3 -m mlab abx-score <folder> <answers>`.

## Interpretation

If supported, the YouTube master should target about -14 LUFS and spend the rest on punch. If the ABX shows no audible difference, loudness is a free choice.

