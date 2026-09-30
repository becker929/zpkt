# H006 — YouTube-style AAC encoding pushes HW002 over 0 dBTP unless the ceiling is lowered

Run 2026-09-26 00:58 · chapter 17-19 / 20-21 · source: true peak / inter-sample peaks; codec behaviour

**Claim.** The demo's true peak is -0.5 dBTP. A 128 kb/s AAC round trip raises it by about 0.5 dB, to or past 0 dBTP. A master limited to -1.5 dBTP stays under 0 after AAC. Level-matched, the AAC version is not reliably distinguishable (ABX).

**Verdict: SUPPORTED**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| loudness.true_peak | as_is_aac − as_is | > | 0.2 | 0.51 | PASS |
| | *codec adds peak* | | | | |
| loudness.true_peak | ceil_-1.5_aac − 0 | < | 0.0 | -1.22 | PASS |
| | *-1.5 dBTP ceiling survives AAC* | | | | |

## Measurements

| metric | as_is | as_is_aac | ceil_-1.5 | ceil_-1.5_aac |
|---|---|---|---|---|
| loudness.true_peak | -0.48 | 0.03 | -1.5 | -1.22 |
| loudness.sample_peak | -0.48 | -0.04 | -1.5 | -1.24 |
| loudness.integrated | -13.84 | -13.93 | -13.85 | -13.94 |
| tonal.group.air | -20.0 | -20.15 | -20.0 | -20.14 |

## Variants

- **as_is**: demo → 
- **as_is_aac**: demo → codec
- **ceil_-1.5**: demo → limiter
- **ceil_-1.5_aac**: ceil_-1.5 → codec

## Listening

Blind ABX kit in `hypotheses/results/H006-aac-adds-overs/abx` (level-matched). Score with `python3 -m mlab abx-score <folder> <answers>`.

## Interpretation

Sets the limiter ceiling for the Short. Re-check with a real YouTube upload: download the served audio and measure it (guides/youtube-short-delivery.md).

