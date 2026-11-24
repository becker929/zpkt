# HW002 Mastering Lab — Index

Goal: finish HW002 and master its YouTube Short ourselves.
This folder holds calibrated measuring tools, guides and a hypothesis runner.
Start here. Agents: read `CLAUDE.md` next.

Lives at `ears/mlab` in the zpkt repo. Started 2026-09-25.
The code is the ears package's calibrated meters, `zpkt.audio.meters` (`src/zpkt/audio/meters/`).
Run the commands below from this folder with `uv run` in front; `mlab` and `ears` take the same commands.

## Start here

| If you want to… | Open |
|---|---|
| Know what state the lab is in | [STATUS.md](STATUS.md) |
| Hand Claude a hypothesis | [hypotheses/TEMPLATE.yaml](hypotheses/TEMPLATE.yaml), then `python3 -m mlab hyp run <file>` |
| Measure a bounce | `python3 -m mlab measure <file.wav>` |
| Review a premaster (checklist + measures + refs + feedback) | `python3 -m mlab review <file.wav>` |
| Check a premaster before mastering | `python3 -m mlab premaster <file.wav>` |
| See what YouTube will do to a master | `python3 -m mlab deliver <file.wav>` |
| Level-matched A/B or blind ABX | `python3 -m mlab abx <a.wav> <b.wav>` |
| Compare a mix with references, build and drop | `python3 -m mlab target <mix.wav> --refs refs.json --set hw002` |
| Fit EQ moves on bus stems to the references | `python3 -m mlab eqfit --stems <a.wav> <b.wav> … --moves moves.json --refs refs.json` |
| Prove the meters are right | `python3 -m mlab calibrate` (writes [calibration/CALIBRATION.md](calibration/CALIBRATION.md)) |
| Look up a term | [GLOSSARY.md](GLOSSARY.md) |
| Read what we have learned | [LEARNINGS.md](LEARNINGS.md) |

## Study subjects → guide → tools

| # | Subject (book chapters) | Guide | Main tools |
|---|---|---|---|
| 1 | Dither & bit depth (Ch. 15) | [guides/ch15-dither.md](guides/ch15-dither.md) | `bitdepth`, `dsp.quantize` |
| 2 | EQ (Ch. 4) | [guides/ch04-eq.md](guides/ch04-eq.md) | `spectrum`, `eq-diff`, `equal-loudness`, `eqfit` |
| 3 | Compression / dynamics (Ch. 5–7) | [guides/ch05-07-dynamics.md](guides/ch05-07-dynamics.md) | `dynamics`, `comp-probe`, `dsp.compressor` |
| 4 | Signal flow & premaster (Ch. 14) | [guides/ch14-signal-flow-premaster.md](guides/ch14-signal-flow-premaster.md) | `premaster`, `als` |
| 5 | Loudness war / metering (Ch. 17–19) | [guides/ch17-19-loudness.md](guides/ch17-19-loudness.md) | `measure`, `deliver` |
| 6 | Monitoring & level-matched comparison (Ch. 20–21) | [guides/ch20-21-monitoring.md](guides/ch20-21-monitoring.md) | `abx`, `match`, `kcal`, `refs`, `target` |

Cross-cutting guides:
[workflow](guides/00-workflow.md) ·
[Ableton Live 12](guides/ableton-live-12.md) ·
[YouTube Short delivery](guides/youtube-short-delivery.md)

## target and eqfit: a mix against references

`mlab target` compares a mix with references, window by window.
Its windows are the 16 bars before the drop (build) and after it (drop).
Spectral values are dB rel LUFS, so shape counts and level does not.
Each window gets 1/3-octave bands, twelve regions, side minus mid, PLR, crest and punch.
Every value shows the references' mean and range, and the mix's distance outside it.
References are listed in a `refs.json`: id, file, drop time, bar length and set.

`mlab eqfit` fits EQ moves on solo renders of the mix's buses.
A moves file says which bands and faders may move, and how far.
It predicts the mix by adding the stems' powers; correlation between stems is ignored.
Its model check compares that prediction with the real stem sum.
eqfit writes a plan; applying it in Live is a separate step.
Code: `src/zpkt/audio/meters/target.py`, `eqfit.py`; known answers in `calibration/checks.py`.

## Folder map

| Path | What |
|---|---|
| `../../src/zpkt/audio/meters/` | The Python instrument package (`zpkt.audio.meters`, also importable as `mlab`). One module per job. |
| `calibration/` | Known-answer tests for every instrument, plus the ffmpeg cross-check. |
| `guides/` | One guide per study subject, plus workflow, Ableton and delivery. |
| `hypotheses/` | Hypothesis files (`H###-*.yaml`) and their `results/`. Inputs come from `$MLAB_DATA` if set, else this folder. |
| `audio/inbox/` | Drop new Ableton exports here. |
| `audio/hw002/` | HW002 source audio (bounces, the 1-minute demo). |
| `audio/refs/` | Reference tracks for comparison. |
| `audio/renders/` | Anything the lab renders (level-matched pairs, codec sims). |
| `reports/` | Measurement sheets, one per file per run. |
| `spikes/` | Throwaway experiments, kept for the record. |
| `.claude/skills/` | Skills for a Claude session working here. |
