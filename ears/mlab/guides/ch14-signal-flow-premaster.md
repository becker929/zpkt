# Subject 4 — Signal flow & premaster (Ch. 14)

Keywords: signal flow, gain staging, premaster checklist, file prep.

## The idea in five sentences

Signal flow is the path from each track through groups and returns to the main bus.
Gain staging keeps every point on that path clear of clipping and clear of noise.
The premaster is the mix as it leaves mixing: no limiter on the main bus, headroom left.
It should be high-resolution, correctly trimmed, and free of clicks, DC and polarity faults.
Mastering starts from this file, so mistakes here cannot be fixed later.

## Instruments

| Command | Answers | Calibration |
|---|---|---|
| `mlab premaster FILE` | PASS/WARN/FAIL per check, with numbers | seven planted faults, each caught |
| `mlab als SET.als` | tempo, tracks, groups, deactivated tracks, every device and whether it is on, main-bus chain, faders | Live 10 and Live 12 fixtures; planted limiter and switched-off plugin flagged |
| `mlab bitdepth FILE` | DC offset and whether it is steady | L-007 |

Premaster checks and their thresholds (`mlab/premaster.py`, `CHECKS`):

| Check | FAIL / WARN when |
|---|---|
| format | lossy = FAIL; 16-bit = WARN |
| sample peak | ≥ -0.01 dBFS FAIL; > -1 dBFS WARN |
| true peak | > 0 dBTP WARN |
| clipped runs | any run of ≥ 3 full-scale samples FAIL |
| PLR | < 8 dB WARN (a limiter is probably on the main bus) |
| DC offset | > -60 dBFS and steady WARN |
| head / tail | first or last 10 ms above -50 dBFS WARN |
| correlation | < 0 FAIL; 20–120 Hz < 0.8 WARN |
| mono-sum loss | > 3 LU WARN |
| L/R balance | > 1.5 dB WARN |
| duration | > 180 s WARN (Shorts limit) |

## HW002 baseline (demo MP3)

FAIL on format (it is an MP3). WARN on peak (-0.48 dBFS), on DC (steady, about -35 dBFS while the kick plays) and on the tail (it ends hard, at -15 dBFS).
PASS on clipping, PLR, polarity, low-end correlation (0.86) and mono loss (0.7 LU).

## The HW002 set, from the site's records

`HW002_14.als`: 160 BPM, 44.1 kHz, 18 tracks (from the multitrack bounce manifest, 2026-09).
Groups: kick group (kick, rumble), perc group, SFX group, Break group; a muted reference track ("Lethal Storm").
Rumble chain: Utility → Shifter → Decapitator → EQ Eight → LFOTool → Utility.
Several tracks run Dist COLDFIRE and ValhallaSupermassive. The kick group had Roar switched off and an idle compressor (site note 10).
The DC offset (L-011) most likely comes from the kick or rumble saturation.

## Premaster recipe for the Short

1. Open a **copy** of the set. Never save over the original.
2. Bypass everything on the Main track that limits or clips. Keep tonal EQ if it is part of the mix.
3. Main fader at 0 dB. Peaks around -6 to -3 dBFS; trim on groups, not on Main.
4. Set the loop brace to the Short's section, plus one bar of pre-roll and the full tail.
5. Export: Rendered Track = Main, 32-bit float, no dither, Normalize off, sample rate = project rate.
6. Drop the file in `audio/inbox/` and run `mlab premaster` and `mlab als` on the copy of the set.

## Sources

- Primary: ITU-R BS.1770-5 (2023) for the true-peak definition (tier 1).
- Expert: site repo `research/live-multitrack-bounce.md` and its MANIFEST (tier 4, this project).
- Secondary: the book's premaster checklist — add its items to `CHECKS` as hypotheses.
