# STATUS — where `PLAN.md` actually stands

Updated 2026-09-08. Read this before picking work up.

| Phase | State |
|---|---|
| 1. Redo everything with the ears lab | **DONE** |
| 2. Housekeeping and provenance | **DONE** |
| 3. Tooling and robustness | **DONE** |
| 4. Validate and harden the map as a control | **IN PROGRESS** (step 1 done) |
| 5. Widen the map | **NOT STARTED** |
| Critic → Assistant → Engineer | Blocked until 4 and 5 land. Do not start early. |

**Live-writing work is currently PAUSED.** Another agent is running a
"multitrack bounce" job on the same shared Live instance. No Live writes
happen here until that's confirmed done. Everything below Phase 4 step 1 is
fully prepped and ready to execute the moment Live is free: see
`PHASE4_5_HANDOFF.md` for the complete, self-contained playbook (9 remaining
Live tasks, 7 of them with ready-to-run `.sweep.json` files already written,
plus the orthogonality-matrix synthesis step which needs no Live at all).

Phases 4 and 5 were not attempted. They are the two phases that require driving
Live for many new bounces, and the session ran out of budget before them. The
foundation they stand on is finished and verified, so they can start cleanly.

---

## Phase 1 — DONE

All six "done when" conditions met. Full write-up: `PHASE1_REPORT.md`.

- Every sweep with audio re-measured with the real `ears` lab into a NEW
  `*.acceptance.ears.csv`; no original CSV overwritten.
- Worst per-column disagreement vs `measure_local` anywhere: **3.175e-08**
  against a 1e-6 budget. `crest` identical bit-for-bit on every row.
  Table re-run from scratch and reproduced to every digit.
- Residual root-caused: real ears loads float32, `measure_local` casts to
  float64. Same band math, different FFT-input rounding. Not a discrepancy.
- Docs now point to ears as the default: `HANDOFF.md` §4/§10/§12, `MAP.md`,
  `README.md`, and `~/.agents/skills/knob-measure-map/SKILL.md` §7.
- `kick_pitch_v1` skipped (known dud). `roar_drive_v1` has zero wavs and cannot
  be measured — logged as a finding.

## Phase 2 — DONE

- Original device state snapshotted to `snapshots/snts_kick_devices.json` and
  round-trip verified by `rig.py restore` (15/15 checks PASS at tol 1e-4).
- Relaunch + rig-rebuild recipe: `PROVENANCE.md` §2–§3.
- Clone provenance: `PROVENANCE.md` §1. The real project is proven untouched by
  **MD5 match**, plus preserved April mtimes and byte sizes.
- Sidecar audit: **zero orphan wavs** across all out dirs. Full spec ↔ out-dir
  index with a one-line finding each: `PROVENANCE.md` §5. Two dirs are
  incomplete by nature (`roar_drive_v1` has no audio; `live_multitrack_bounce_v1`
  is empty) — both documented rather than silently deleted.
- ears lab home decided and written down: stays in `_agent_scratch`, but nothing
  depends on it, because the in-repo `ears_shim.py` degrades to `measure_local`.
  Rebuild command + the 8 resolved versions + the `uv.lock` pin: `PROVENANCE.md` §6.

## Phase 3 — DONE

All six items, each verified by actually running it.

| Item | Result |
|---|---|
| 1. Explicit `values` list | `run_sweep_stem.py` uses `values` verbatim when present; duplicates preserved (that is how Phase 4's repeat test works). All 9 existing specs produce IDENTICAL grids before/after. |
| 2. Column-shift fix | CSV is now `QUOTE_ALL`, plus a pre-aligned `*.acceptance.txt` view rendering blanks as `-`. `assemble_curve.py` prints "read THIS by eye; do NOT `column -t` the CSV". |
| 3. Silent-bounce guard | Fails fast on size (`--min-wav-kb`, 50) or peak (`--min-peak-dbfs`, −60), deletes the dead wav, writes no sidecar, names the likely rig cause. `--allow-silent` escapes. Handles 24-bit (the real bounce format). |
| 4. Curve auto-summary | `summarize_curve.py`: direction, extrema + where, span, invertible region(s), match vs `predicted_direction`. |
| 5. Rig setup/teardown | `rig.py snapshot` / `solo-device` / `restore`, all read-back verified, nonzero exit on mismatch. |
| 6. Regression test | `test_measure_agreement.py` PASSES; all 6 columns within 1e-6. Failure path and skip path both exercised. |

Verified end to end on Live: the `values`-list demo bounced two real non-silent
stems, and **track 6 was left byte-identical to the original snapshot**.

### Two useful accidents worth keeping

1. **A cross-session reproducibility measurement.** The Phase-3 demo re-bounced
   Clipping 0.750 / 0.782, which `snts_kick_clip_validate_v1` had already
   bounced in an earlier session on a hand-built rig. crest agreed to **0.014
   and 0.015 dB**; peak dBFS agreed to 0.01 dB. So the set→bounce→measure chain
   is stable, and `rig.py solo-device` rebuilt the Row-2 rig faithfully. This is
   recorded in `MAP.md` as a **PROVISIONAL n=2 crest error bar of ~0.02 dB**.
2. **`summarize_curve.py` needed a tolerance.** Real bounces jitter, so a
   zero-tolerance monotonicity test calls *every* curve non-monotonic. It judges
   direction inside a noise band (default 10% of the column's span, or `--tol`
   for an absolute bar) and always prints the strict verdict too, so noise stays
   visible. Once Phase 4 step 1 gives a real error bar, pass it as `--tol`.

---

## Start Phase 4 here

Phase 4 step 1 (crest noise, 5 repeats at one fixed setting) is now a one-liner,
because Phase 3 shipped the explicit `values` list and duplicates are preserved:

```json
"values": [0.766, 0.766, 0.766, 0.766, 0.766]
```

Then:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/rig.py solo-device --track 6 --device 6 --name p4_noise
timeout 900 uv run python sweeps/run_sweep_stem.py --sweep sweeps/<new>.sweep.json \
  --capture-track 44 --source-track 6 --source-input "Kick (G)"
export EARS_CMD="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/ears"
uv run python sweeps/assemble_curve.py --dir sweeps/out/<id> \
  --ears-cmd "uv run python sweeps/ears_shim.py" \
  --measure-keys crest_db sub_share low_share mid_share high_share air_share \
  --out sweeps/out/<id>/<id>.acceptance.ears.csv
uv run python sweeps/summarize_curve.py --csv sweeps/out/<id>/<id>.acceptance.ears.csv
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

**DONE (this session).** Ran `p4_noise.sweep.json` (5 repeats, Clipping
0.766). Row 0 was a cold-start artifact — a 250 s bounce instead of ~3.6 s,
excluded and logged as an open finding, not a tooling fix. The 4 clean crest
values (5.972, 5.861, 5.888, 5.888 dB) give **stdev 0.048 dB, range 0.111
dB** — wider than the n=2 provisional 0.02 dB, as `PLAN.md` warned it might
be. Written into `MAP.md` and `HANDOFF.md` §4. Rig restored and verified
15/15 PASS; a fresh snapshot diffed byte-identical to the original (only the
timestamp differed). **Use `--tol 0.05` on `summarize_curve.py` going
forward.**

Remaining Phase 4 steps, unchanged from `PLAN.md`: validate the clipper
floor/ceiling rows (targets 4.5, 8.0, 8.5 dB) and label the saturating ones;
validate the Transient Attack inverse in its clean 0.5..0.9 region; test whether
two knobs compose; re-run the clipper validation with Decapitator left ON to test
portability; fine-sweep Attack 0.5..0.9 at 0.025 to confirm the 0.9 peak is real
and not a coarse-grid artifact (the Decap hump taught us to check — treat the
coarse-grid 0.9 peak as UNCONFIRMED until step 6 runs).
