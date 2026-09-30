---
name: mastering-lab
description: Measure, check or compare audio for the HW002 mastering project with the calibrated mlab instruments (LUFS, true peak, dynamics, tonal balance, dither, premaster, YouTube delivery, ABX). Use for any mastering measurement, premaster check or level-matched comparison in this lab.
---

# Mastering lab: operate the instruments

Lab root: `~/Music/hw002-mastering-lab` (in a Cowork shell: `$HOME/mnt/Music/hw002-mastering-lab`).
Read `CLAUDE.md` and `STATUS.md` first. Run everything from the lab root.

## Before trusting a number

1. `python3 -m pytest calibration -q` must pass (82 known-answer tests; `python3 -m mlab calibrate` adds 12 cross-checks).
2. After changing any file in `mlab/`, rerun it. After adding a meter, add its check to
   `calibration/checks.py` first (known answer, tolerance, basis).

## Pick the tool

| Question | Command |
|---|---|
| How loud / how limited / how punchy? | `python3 -m mlab measure FILE` (sheet in `reports/`) |
| Is this file fit to master? | `python3 -m mlab premaster FILE` |
| What will YouTube and codecs do? | `python3 -m mlab deliver FILE` |
| Word length, dither, DC? | `python3 -m mlab bitdepth FILE` |
| Tonal balance, vs a reference, at another listening level? | `python3 -m mlab spectrum FILE [--ref R] [--phon 60]` |
| What did a Live EQ / compressor really do? | `python3 -m mlab probe`, render in Live, then `eq-diff` / `comp-probe` |
| Which version is better? | `python3 -m mlab match A B` or `python3 -m mlab abx A B` |
| What is in the set? | `python3 -m mlab als SET.als` (a copy, never the original) |

## Report like this

Numbers first, with units. Then one line on what they mean. Then what would change it.
Name the learning ID (L-###) you rely on, and add a new one if something surprised you.
Every A/B is level-matched unless the question is about level.

## Known limits

- The Cowork shell is a Linux VM: it cannot drive Ableton. Renders come from Anthony or a native session.
- `dsp.compressor` / `dsp.limiter` are reference designs, not Live's devices.
- Platform loudness behaviour is observed, not documented; YouTube = -14 LUFS, turn-down only.
- MP3 inputs hide word length and dither. Ask for the WAV export.
