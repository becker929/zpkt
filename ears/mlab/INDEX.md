# HW002 Mastering Lab — Index

Goal: finish HW002 and master its YouTube Short ourselves.
This folder holds calibrated measuring tools, guides and a hypothesis runner.
Start here. Agents: read `CLAUDE.md` next.

Lives at `~/Music/hw002-mastering-lab` on the Mac mini.
Started 2026-09-25.

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
| Prove the meters are right | `python3 -m mlab calibrate` (writes [calibration/CALIBRATION.md](calibration/CALIBRATION.md)) |
| Look up a term | [GLOSSARY.md](GLOSSARY.md) |
| Read what we have learned | [LEARNINGS.md](LEARNINGS.md) |

## Study subjects → guide → tools

| # | Subject (book chapters) | Guide | Main tools |
|---|---|---|---|
| 1 | Dither & bit depth (Ch. 15) | [guides/ch15-dither.md](guides/ch15-dither.md) | `bitdepth`, `dsp.quantize` |
| 2 | EQ (Ch. 4) | [guides/ch04-eq.md](guides/ch04-eq.md) | `spectrum`, `eq-diff`, `equal-loudness` |
| 3 | Compression / dynamics (Ch. 5–7) | [guides/ch05-07-dynamics.md](guides/ch05-07-dynamics.md) | `dynamics`, `comp-probe`, `dsp.compressor` |
| 4 | Signal flow & premaster (Ch. 14) | [guides/ch14-signal-flow-premaster.md](guides/ch14-signal-flow-premaster.md) | `premaster`, `als` |
| 5 | Loudness war / metering (Ch. 17–19) | [guides/ch17-19-loudness.md](guides/ch17-19-loudness.md) | `measure`, `deliver` |
| 6 | Monitoring & level-matched comparison (Ch. 20–21) | [guides/ch20-21-monitoring.md](guides/ch20-21-monitoring.md) | `abx`, `match`, `kcal`, `refs` |

Cross-cutting guides:
[workflow](guides/00-workflow.md) ·
[Ableton Live 12](guides/ableton-live-12.md) ·
[YouTube Short delivery](guides/youtube-short-delivery.md)

## Folder map

| Path | What |
|---|---|
| `mlab/` | The Python instrument package. One module per job. |
| `calibration/` | Known-answer tests for every instrument, plus the ffmpeg cross-check. |
| `guides/` | One guide per study subject, plus workflow, Ableton and delivery. |
| `hypotheses/` | Hypothesis files (`H###-*.yaml`) and their `results/`. |
| `audio/inbox/` | Drop new Ableton exports here. |
| `audio/hw002/` | HW002 source audio (bounces, the 1-minute demo). |
| `audio/refs/` | Reference tracks for comparison. |
| `audio/renders/` | Anything the lab renders (level-matched pairs, codec sims). |
| `reports/` | Measurement sheets, one per file per run. |
| `spikes/` | Throwaway experiments, kept for the record. |
| `.claude/skills/` | Skills for a Claude session working here. |
