# Spike: hill-climbing HW002 mix alternates toward the references

Started 6 October 2026. Published as /skrng batch 5 (site PRs #47, #48, #49).
Audio and measurements stay private in `~/_agent_scratch/mixclimb/`.

## What it does

Six mix changes for the canonical shape (batch 4.3 track 1), each tuned on its own.
Targets come from the four Bandcamp references' 30 s peak windows.
Features: mlab's calibrated meters plus the level-free `ears` spectral features.
Everything is measured at -14 LUFS, so loudness cancels out.

The score has two parts. The first is the distance to the reference range and mean on the aspect's own features.
The second is a penalty for any other feature that ends up further from the references than the original was.
Each batch-attempt tries eight Gaussian steps around the current best.
An aspect has plateaued after ten batch-attempts in a row with no new high score.

## Run it

```
# 1. stems from a built version set (Live, ~5 min): mix + one stem per group
cd hands && PYTHONPATH=scripts/arrange_prototype uv run python scripts/arrange_prototype/stems.py \
  --from-set HW002_121_v_b43-01-splash-every-8-bars-30s 22 \
  '{"start_bar": 1, "proc": [3, 20], "meas": [5, 20], "ab": [5, 12], "ab_label": "..."}'
# 2. targets, then one climb per aspect (offline, inside ears/mlab)
uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/targets.py
uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/climb.py kick_distortion
# 3. publish batch 5: branch, upload, PR, merge, verify live
spikes/hw002_mixclimb/publish_cycle.sh TAG
```

## Result (6 October)

| Aspect | Change found | Score (0 = matches the references) |
|---|---|---|
| Kick distortion | Mono, clean below 60 Hz: +12 dB at 1.6 kHz into 23 dB drive, fully wet | -2.46 to -1.05 |
| Drop power | Drum bus mid: 8.9 dB soft clip, 36% parallel compression | -2.83 to -1.17 |
| Deep sub | +8.7 dB at 29 Hz on the kick bus | -1.87 to -0.49 |
| Mono low end | Side signal down 60 dB below 136 Hz | -2.94 to -0.59 |
| Colour | +6 dB at 1.6 kHz, -4.8 dB shelf from 5.5 kHz | -1.41 to -0.34 |
| Space | Perc bus reverb, size 0.72, 29% wet | -0.34 to -0.27 |

Several settings ended at the edge of their allowed range (kick emphasis, wet mix, compressor).
The references may want more than these ranges allow.

## Lessons

- Drive each channel separately and the low end decorrelates. Distort the mid only, and keep the sub clean.
- Stems never null against a mix take (L-018). Check them by feature agreement.
- A guard on every feature blocked the kick change: mono knock narrows the 500 Hz-2 kHz band.
  Width belongs to the space aspect, so the kick guard skips width above 120 Hz.
