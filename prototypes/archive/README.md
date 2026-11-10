# archive

Scripts kept for reference, unmaintained. They made the HW002 batches and studies of September and
October 2026, and they record how each one was made. They are not tested, and most no longer run:
they import modules by path (`arrange`, `pp`, `probe_kit`, `als_probe`) that moved into the `hands`
library in October 2026, and their paths and set names are hard-coded. Read them; build new work on
the library.

| Folder | What it made | Where that lives now |
|---|---|---|
| `arrange_prototype/` | arrangement batches 2-4.4: cut the set (Delete Time), restore automation, record in real time, trim and verify the takes, build the /skrng entries; plans as JSON | `hands.live.timeops`, `hands.arrange` (fx, autostate.restore, hats), `hands.live.record`, `hands.audio` (trim_take, best_lag, timeline_check) |
| `probe_pack/` | the probe-packing benches (`bench_*`) and the batch 6-7 one-offs (`combine_live`, `sweep_live`) | `hands.probe_kit`, `hands.als`; findings in `../docs/probe-packing-findings.md` |
| `sweeps/` | the knob-to-measure sweep harness and its results (September 2026), incl. scripts that call a skill path that no longer exists | `hands.live.knobs` for setting knobs; the results stay here |

The batch-8 scripts that still run are in `../scripts/probe_pack/` (`sweep8.py`, `ab_live.py`,
`climb_live.py`).
