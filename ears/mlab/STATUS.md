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
| H006 | Loudness / monitoring | AAC adds overs; -1.5 dBTP survives | SUPPORTED on the container's ffmpeg, NOT SUPPORTED on the Mac's ffmpeg 4.4 (overs are encoder-specific); the -1.5 dBTP part held on both | L-013, L-017 |

Blind ABX kits (A, B, X01–X12, HOW_TO.md) are waiting for H001, H002, H004, H005 and H006
in `hypotheses/results/<id>/abx/`. Hypothesis audio is float WAV, about 900 MB in total;
`hypotheses/results/*/audio/` can be deleted and regenerated at any time.

Also ready on disk: probe signals (`audio/renders/probes/`) and K-System calibration
noise (`audio/renders/k-system/`). Last full calibration on the Mac: 94/94.

## What the demo says so far

The demo sits at -13.8 LUFS, -0.48 dBTP. YouTube would barely touch it.
Its loudest moment is a breakdown event at 33–34.5 s, 4–6 dB above typical kick peaks.
There is a steady DC offset while the kick plays, a low-mid hole, and a hard cut at the end.

## Plan (agreed 2026-09-26)

1. Anthony sets up Ableton Live on this Mac mini.
2. Anthony cuts the HW002 Short version, compresses the loud breakdown event (33–34.5 s in the demo),
   and bounces a premaster: Main, 32-bit float, no dither, Normalize off, main-bus limiter off,
   one bar pre-roll and the full tail. File goes in `audio/inbox/`.
3. Anthony adds 3–5 references (WAV/FLAC preferred; MP3 320 is fine) to `audio/refs/`.
4. Claude runs `python3 -m mlab review audio/inbox/<file>.wav` and gives feedback
   (report in `reports/review-<file>.md`).
5. Claude drives Live with the Ableton skill Anthony provides and renders a few master versions
   (hypotheses H010+), each measured and loudness-matched.
6. Anthony listens (ABX kits) and we decide the next move.

## Next for Claude

- Rerun H001–H006 on the WAV premaster when it lands.
- Build the device map from probe renders.
- Draft the Short's master chain as a hypothesis set (H010+), then ABX against the demo.
- After the first unlisted upload, check the YouTube model (guides/youtube-short-delivery.md).
