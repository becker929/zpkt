# Working in the HW002 mastering lab

You are helping Anthony master HW002 for a YouTube Short.
He studies a mastering book and brings hypotheses from it.
Your job: turn each hypothesis into a measured, level-matched experiment.
Report numbers first, then what they mean.

## Who and what

- Anthony makes industrial hard techno in Ableton Live 12 Suite.
- HW002: 160 BPM, 44.1 kHz. A 1-minute demo exists (`audio/hw002/`).
- The published notes are at anthonybecker.me/notes. The research code is
  in `github.com/becker929/anthonybecker.me` under `research/sound-function/repo`.
- `github.com/becker929/ears` is the older perception layer. Its loudness
  numbers are NOT calibrated (see LEARNINGS.md, L-003). Use `mlab` instead.

## Commands

```
python3 -m mlab calibrate                 # run all known-answer tests, write calibration/CALIBRATION.md
python3 -m mlab measure FILE [--json]     # loudness, peaks, dynamics, spectrum summary
python3 -m mlab premaster FILE            # Ch.14 checklist: PASS / WARN / FAIL per item
python3 -m mlab deliver FILE              # YouTube Short: normalization + codec round-trip
python3 -m mlab bitdepth FILE             # effective bits, dither detection, DC
python3 -m mlab spectrum FILE [--ref R]   # 1/3-octave tonal balance, optional vs reference
python3 -m mlab eq-diff DRY WET           # the EQ curve a device actually applied
python3 -m mlab comp-probe DRY WET        # gain-reduction curve, threshold/ratio/attack/release estimate
python3 -m mlab match A B [...]           # write loudness-matched copies to audio/renders/
python3 -m mlab abx A B                   # blind ABX session files + answer key
python3 -m mlab kcal                      # K-System pink-noise calibration files
python3 -m mlab als FILE.als              # Ableton set: tempo, tracks, main-bus chain
python3 -m mlab hyp run hypotheses/H###.yaml
python3 -m pytest calibration -q          # same checks as `calibrate`, as tests
```

Install once: `pip install -r requirements.txt` (numpy, scipy, soundfile, pyloudnorm, pyyaml, pytest).
ffmpeg is needed for mp3/m4a input, codec simulation and the cross-check.

## Rules

1. **Calibrate before you trust.** Every instrument has a known-answer test.
   If you add or change a meter, add its test in `calibration/` first.
   The research history is "every ruler bent when it touched real audio"
   (note: three-wrong-rulers). Assume yours will too.
2. **Level-match every comparison.** Louder sounds better. Any A/B of two
   versions uses integrated-LUFS matching unless the hypothesis is *about* level.
3. **Never modify Anthony's originals.** Ableton sets are opened as copies.
   Audio in `audio/hw002/` is read-only by convention. Write to `audio/renders/`.
4. **Write down what you learn.** Every surprising result gets an entry in
   `LEARNINGS.md` with date, evidence and what it changes.
5. **Say which source tier a claim rests on.** Standards (ITU, EBU, ISO, AES)
   beat manuals, which beat blogs. Platform loudness behaviour is mostly
   observed, not documented; say so.
6. **Mono-sum, codec and phone checks** are part of every delivery check.
   A Short is heard on phones first.
7. Prose docs follow 6-15-1: ≤6 sentences per paragraph, ≤15 words per
   sentence, one idea per sentence. New terms go in GLOSSARY.md.

## Where things run

- Anthony's Mac mini. The Cowork shell there is a **Linux VM**, not macOS.
  It sees only connected folders (`~/Music`). It cannot drive Ableton.
- Driving Live (OSC + LOM) needs a native session on the Mac. The earlier
  rig's skill is at `~/.agents/skills/ableton-live-control/` on the Mac that
  holds `~/_tmsmsm/`. See `guides/ableton-live-12.md` for the hand-off.
- Cowork shell limits (learned 2026-09-25): each call ends after 180 s and kills any
  background process it started; run one hypothesis per call (all six run in 12-40 s each).
  Deletes are not permitted by default, so update files with `tar --overwrite -xzf ...`
  and run pytest with `-p no:cacheprovider`.
- Anthony's Drive holds `HW002_1min-2026-08-13T2107.mp3`, `HW002_9.mp3`
  and `HW002.zip`. The Drive connector downloads files ≤10 MB only.

## Hypothesis workflow (the main loop)

1. Anthony states a claim from the book.
2. Copy `hypotheses/TEMPLATE.yaml` → `hypotheses/H###-slug.yaml`. Fill in
   claim, chapter, variants, the metric that decides it, and the threshold.
3. `python3 -m mlab hyp run hypotheses/H###-slug.yaml`
4. Read `hypotheses/results/H###-slug/report.md`. Add a listening step
   (ABX) if the claim is about audibility.
5. Log the verdict in LEARNINGS.md and STATUS.md.
