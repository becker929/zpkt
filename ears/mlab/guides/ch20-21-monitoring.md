# Subject 6 — Monitoring & level-matched comparison (Ch. 20–21)

Keywords: monitor calibration, listening level, A/B, level matching, reference tracks, K-System.

## The idea in six sentences

A version that is 1 dB louder usually sounds better, even when nothing else changed.
So every comparison must be level-matched, or it measures loudness, not quality.
Blind ABX tests show whether a difference is heard at all.
A fixed, calibrated monitor gain makes loudness something you can hear reliably.
The K-System ties that gain to a meter scale: K-20, K-14 or K-12.
Reference tracks, level-matched, show where your master sits in its genre.

## Instruments

| Command | Answers | Calibration |
|---|---|---|
| `mlab match A B …` | copies at equal integrated loudness (quietest wins) | equal within 0.01 LU |
| `mlab abx A B [--start s --dur s]` | a blind kit: A, B, 12 shuffled X files, a sealed key | — |
| `mlab abx-score FOLDER ANSWERS` | correct count and p-value | binomial: 10/12 → p = 0.019; 9/12 → p = 0.073 |
| `mlab kcal` | pink noise for K-20 / K-14 / K-12, full band and 500 Hz–2 kHz, left and right | RMS set by construction |
| `mlab refs FILE audio/refs/` | your file against references on the core measures | inherits each meter's calibration |
| `dynamics` keys `k20_rms_db`, `k14_rms_db` | where the file would sit on a K-meter | sine-referenced RMS (AES-17) |

## K-System calibration, step by step

1. Run `python3 -m mlab kcal`. Files land in `audio/renders/k-system/`.
2. Pick K-14 for this music. (K-20 suits wide-dynamic material.)
3. Play `K-14_500-2k_L.wav` on the left monitor only.
4. With a phone SPL app (C-weighting, slow), set the monitor gain for 83 dB SPL at the listening spot.
5. Repeat for the right. Mark the volume knob position.
6. Mix and compare at that mark. A master that feels right there lands near K-14.

The files follow the sine-referenced (AES-17) RMS convention used by K-meters.
Plain RMS of the noise is 3 dB lower. Some guides skip that; it shifts the result by 3 dB.
Phone SPL apps are rough (±2–3 dB). Consistency matters more than accuracy here.

## HW002 baseline

On a K-14 scale the demo's average RMS reads +1.7 (dynamics `k14_rms_db`).
It is hotter than the K-14 zero, typical for this genre.

## Experiments ready to run

- *The loudness bias test*: `mlab abx` on the demo and a +1 dB copy (`gain` op). You will probably prefer the louder one. That is the point.
- **H006** ABX: is AAC 128 k audible at matched level?
- *Phone check*: add an `eq` variant with a highpass at 150 Hz and lowpass at 12 kHz as a rough phone speaker. Compare kick balance.
- *References*: 3–5 tracks (e.g. the muted "Lethal Storm" in the set, and the references from site note 3) into `audio/refs/`.

## Sources

- Primary: B. Katz, "An Integrated Approach to Metering, Monitoring, and Leveling Practices", *JAES* 48(9), 2000 (tier 2).
- Primary: AES17, measurement of digital audio equipment (RMS convention) (tier 1).
- Secondary: F. Toole, *Sound Reproduction*, 3rd ed., 2017 — listening tests and level bias (tier 3).
- Reference: Wikipedia, "ABX test" (tier 3).
