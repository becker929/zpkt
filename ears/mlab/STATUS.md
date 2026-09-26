# Status — 2026-09-25

## Ready

- **Instruments** for all six subjects (`mlab/`), one CLI (`python3 -m mlab …`).
- **Calibration**: 94 known-answer checks, all passing, against EBU 3341/3342, BS.1770, ISO 226,
  analytic cases, planted faults, and cross-checks with pyloudnorm and ffmpeg.
  Latest: see `calibration/CALIBRATION.md`. Tests: `python3 -m pytest calibration -q`.
- **Hypothesis runner** with a template and six worked hypotheses on the HW002 demo.
- **Guides**: one per subject, plus workflow, Ableton Live 12 and YouTube Short delivery.
- **Skills** in `.claude/skills/`: `mastering-lab` (operate) and `book-hypothesis` (claim → verdict).
- Runs on the Mac mini's Cowork shell (Linux VM, Python 3.10) and in the cloud container.

## Hypotheses so far

| ID | Subject | Claim (short) | Verdict | Learning |
|---|---|---|---|---|
| H001 | Loudness | -9 LUFS gains nothing on YouTube, costs PLR and punch | INCONCLUSIVE: loudness and PLR parts held; punch did not move (0.0 dB, a tie) | L-010 |
| H002 | Dither | 16-bit TPDF floor is far below the programme | SUPPORTED (MP3 caveat) | L-014 |
| H003 | Premaster | 15 Hz high-pass removes DC and frees ≥0.2 dB headroom | NOT SUPPORTED (DC gone, peak +0.1 dB) | L-011 |
| H004 | EQ | Low-mid hole; +3 dB at 350 Hz fills it | SUPPORTED (ABX pending) | L-012 |
| H005 | Dynamics | Slow attack keeps more punch at matched loudness | NOT SUPPORTED with the Python compressor (+0.16 dB, needed +0.5) | L-015 |
| H006 | Loudness / monitoring | AAC adds overs; -1.5 dBTP survives | SUPPORTED (ABX pending) | L-013 |

ABX kits are waiting in `hypotheses/results/H00*/abx/`.

## What the demo says so far

The demo sits at -13.8 LUFS, -0.48 dBTP. YouTube would barely touch it.
Its loudest moment is a breakdown event at 33–34.5 s, 4–6 dB above typical kick peaks.
There is a steady DC offset while the kick plays, a low-mid hole, and a hard cut at the end.

## Blocked on Anthony (in order of value)

1. **A 24-bit or float premaster of the Short section**, main-bus limiter bypassed,
   into `audio/inbox/`. Replaces the MP3 for every measurement.
2. **3–5 reference tracks** into `audio/refs/` (e.g. "Lethal Storm", "Eternal Dream").
   Tonal and dynamics numbers mean little without them.
3. **Connect `~/_tmsmsm/Active Tracks/HW002`** with "Add folder" in the desktop app,
   so `mlab als` can read the set (L-001).
4. **Five ABX sessions** (H001, H004, H005, H006, and a +1 dB bias test). About 25 minutes.
5. **Probe renders** through Glue Compressor, Limiter and EQ Eight (guides/ableton-live-12.md).
6. **K-14 monitor calibration** with `mlab kcal` (guides/ch20-21-monitoring.md).

## Next for Claude

- Rerun H001–H006 on the WAV premaster when it lands.
- Build the device map from probe renders.
- Draft the Short's master chain as a hypothesis set (H010+), then ABX against the demo.
- After the first unlisted upload, check the YouTube model (guides/youtube-short-delivery.md).
