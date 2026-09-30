# H004 — HW002 has a low-mid hole (250-500 Hz) that a broad 3 dB lift fills without costing loudness headroom

Run 2026-09-26 00:57 · chapter 4 · source: EQ chapter (tonal balance, midrange); note 2 'a hole in the middle'

**Claim.** The 250-500 Hz region sits at least 5 dB under both the bass and the mid regions. A broad bell (+3 dB, 350 Hz, Q 0.7) narrows that gap by at least 1.5 dB. Level-matched, the lifted version may or may not be preferred; the ABX decides.

**Verdict: SUPPORTED**

## Predictions

| metric | left − right | op | threshold | observed | status |
|---|---|---|---|---|---|
| tonal.group.low_mid | as_is − 0 | < | -12 | -15.36 | PASS |
| | *low-mid share is small in absolute terms* | | | | |
| tonal.group.low_mid | lowmid_+3 − as_is | > | 1.5 | 2.15 | PASS |
| | *the bell fills it* | | | | |

## Measurements

| metric | as_is | lowmid_+3 |
|---|---|---|
| tonal.group.sub | -7.42 | -7.87 |
| tonal.group.bass | -2.67 | -2.72 |
| tonal.group.low_mid | -15.36 | -13.21 |
| tonal.group.mid | -8.79 | -8.26 |
| tonal.group.upper_mid | -15.19 | -15.68 |
| tonal.slope_db_per_oct | -4.23 | -4.55 |
| loudness.integrated | -13.84 | -13.84 |
| loudness.true_peak | -0.48 | 0.03 |

## Variants

- **as_is**: demo → 
- **lowmid_+3**: demo → eq → normalize_lufs

## Listening

Blind ABX kit in `hypotheses/results/H004-low-mid-hole/abx` (level-matched). Score with `python3 -m mlab abx-score <folder> <answers>`.

## Interpretation

Absolute band shares only mean something against references in the genre. Put 3-5 reference tracks in audio/refs/ and run 'python3 -m mlab refs <file> audio/refs'.

