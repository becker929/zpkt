# H002 — 16-bit TPDF dither on HW002 sits far below anything audible in the programme

Run 2026-09-26 00:57 · chapter 15 · source: dither and word length chapter

**Claim.** Reducing HW002 to 16 bits with TPDF dither adds a noise floor near -96 dBFS. The demo's quietest 100 ms blocks are so much louder that the floor is masked. Truncation instead of dither makes no loudness difference either, at this level.

**Verdict: SUPPORTED**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| word_length.quietest_blocks_dbfs | as_is − 0 | > | -56 | -21.88 | PASS |
| | *quietest passages at least 40 dB above the 16-bit TPDF floor (-96.3 dBFS)* | | | | |
| loudness.integrated | q16_tpdf − as_is | abs< | 0.05 | 0.0 | PASS |
| | *dither noise does not move loudness* | | | | |
| word_length.effective_bits | q16_tpdf − 0 | <= | 16 | 16.0 | PASS |
| | *sanity: the reduction really happened* | | | | |

## Measurements

| metric | as_is | q16_tpdf | q16_truncated |
|---|---|---|---|
| loudness.integrated | -13.84 | -13.84 | -13.84 |
| loudness.true_peak | -0.48 | -0.48 | -0.48 |
| word_length.effective_bits | None | 16 | 16 |
| word_length.quietest_blocks_dbfs | -21.88 | -21.88 | -21.88 |
| tonal.group.air | -20.0 | -20.0 | -20.0 |

## Variants

- **as_is**: demo → 
- **q16_tpdf**: demo → quantize
- **q16_truncated**: demo → truncate

## Listening

Blind ABX kit in `hypotheses/results/H002-dither-16bit-inaudible/abx` (level-matched). Score with `python3 -m mlab abx-score <folder> <answers>`.

## Interpretation

Caveat: the source is a 320 kb/s MP3, whose own coding noise is far above 16-bit dither. Re-run on the 24-bit WAV export. Dither matters most in fades and breakdown tails; test the breakdown (24-47 s) specifically.

