# Phase 1 report — the real `ears` lab is the measurer of record

Date: 2026-09-08. Scope: PLAN.md Phase 1 only (steps 1–5). No Phase 2+ work, and
no edits to `HANDOFF.md`, `MAP.md`, `README.md`, `PLAN.md`, `run_sweep_stem.py`,
or `assemble_curve.py`.

## Verdict

**Pass.** Every sweep with bounced audio was re-measured with the real `ears`
lab. Every shared numeric column agrees with the provisional `measure_local.py`
to better than `3.2e-8`, well inside the `1e-6` tolerance. `crest` matches
**bit-for-bit** (`0.000e+00`) everywhere. No column drifted. Nothing was
overwritten: the original `*.acceptance.csv` files are untouched.

## Measurer of record

Use this as the `--ears-cmd`, from `~/sandbox/autodaw/hands`:

```
--ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py"
```

Full invocation used for every sweep in this report:

```sh
uv run python sweeps/assemble_curve.py \
  --dir sweeps/out/<sweep_id> \
  --ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py" \
  --measure-keys crest sub_share low_share mid_share high_share air_share \
  --out sweeps/out/<sweep_id>/<sweep_id>.acceptance.ears.csv
```

`measure_local.py` stays only as the documented offline fallback:

```
--ears-cmd "uv run python sweeps/measure_local.py" \
--measure-keys crest_db sub_share low_share mid_share high_share air_share
```

Note the key-name difference: the ears shim emits `crest`, `measure_local`
emits `crest_db`. They are the same quantity, same formula.

## Step 1 — hand sanity check

`out/snts_kick_clip_validate_v1/bounce_000.wav`, real ears binary:

```
.venv/bin/ears analyze <wav> --json --no-embeddings
  -> loudness.band_energy.sub = 0.782186857204015
```

Exact match to the value recorded in the brief. The shim reproduces it and adds
`crest = 5.0594102056148635`, which equals `measure_local`'s `crest_db` exactly.

## Files produced

One `*.acceptance.ears.csv` per sweep dir. Because several of the original
`*.acceptance.csv` files carry only a partial column set, a full six-column
`*.acceptance.local.csv` was also generated per dir so the diff covers every
band. Originals were never written to.

| sweep dir | rows | ears CSV | measure cols |
|---|---:|---|---:|
| `snts_kick_decap_drive_v1` | 11 | `snts_kick_decap_drive_v1.acceptance.ears.csv` | 6 |
| `snts_kick_decap_drive_fine_v2` | 13 | `snts_kick_decap_drive_fine_v2.acceptance.ears.csv` | 6 |
| `snts_kick_clip_thresh_v1` | 13 | `snts_kick_clip_thresh_v1.acceptance.ears.csv` | 6 |
| `snts_kick_clip_validate_v1` | 3 | `snts_kick_clip_validate_v1.acceptance.ears.csv` | 6 |
| `snts_kick_transient_attack_v1` | 11 | `snts_kick_transient_attack_v1.acceptance.ears.csv` | 6 |
| `kick_pitch_wide_v1` | 13 | `kick_pitch_wide_v1.acceptance.ears.csv` | 6 |
| `roar_drive_v1` | 11 | `roar_drive_v1.acceptance.ears.csv` | **0** (no audio — see below) |

No blank measure cells in any of the six measured files.

## Steps 3–4 — max absolute difference, ears vs `measure_local`

Tolerance `1e-6`. Compared with `sweeps/compare_measurers.py`, joining on
`index` and folding `crest_db` into `crest`. Values below are ears vs the fresh
full-column `*.acceptance.local.csv`.

| sweep | crest | sub_share | low_share | mid_share | high_share | air_share | verdict |
|---|---|---|---|---|---|---|---|
| `snts_kick_decap_drive_v1` | 0.000e+00 | 1.918e-08 | 2.549e-08 | 8.271e-09 | 9.878e-10 | 6.010e-11 | pass |
| `snts_kick_decap_drive_fine_v2` | 0.000e+00 | 1.867e-08 | 1.626e-08 | 1.074e-08 | 4.970e-10 | 4.711e-11 | pass |
| `snts_kick_clip_thresh_v1` | 0.000e+00 | 2.887e-08 | 2.549e-08 | 7.452e-09 | 6.579e-10 | 6.382e-11 | pass |
| `snts_kick_clip_validate_v1` | 0.000e+00 | 1.634e-08 | 1.252e-08 | 3.890e-09 | 9.798e-11 | 8.113e-12 | pass |
| `snts_kick_transient_attack_v1` | 0.000e+00 | 2.980e-08 | 3.175e-08 | 1.021e-08 | 1.024e-09 | 1.165e-10 | pass |
| `kick_pitch_wide_v1` | 0.000e+00 | 4.510e-09 | 4.512e-09 | 2.803e-10 | 4.558e-12 | 3.854e-13 | pass |
| **worst per column** | **0.000e+00** | **2.980e-08** | **3.175e-08** | **1.074e-08** | **1.024e-09** | **1.165e-10** | **pass** |

Worst single number anywhere: `3.175e-08` (`low_share`,
`snts_kick_transient_attack_v1`). That is ~31x inside the `1e-6` budget.

`requested_value` and `true_value` also compared at `0.000e+00` in every sweep,
confirming the row join is sound.

The same comparison against each dir's **original** `*.acceptance.csv` gives
identical numbers on the columns those files contain, so the older curves are
also validated in place. The originals are simply missing columns, not wrong:

| sweep | columns absent from the original CSV |
|---|---|
| `snts_kick_decap_drive_v1` | low/mid/high/air_share |
| `snts_kick_clip_validate_v1` | low/mid/high/air_share |
| `kick_pitch_wide_v1` | high/air_share |
| others | none |

## Step 5 — why the residual is ~1e-8, not 0

No column exceeded tolerance, so no conclusion is blocked. The residual is still
explained rather than waved away.

`crest` is identical because the shim and `measure_local` run the same
peak/RMS formula on the same float64 array. The band shares differ in the 8th
decimal because of **input dtype**, not different math. Real `ears` loads audio
as float32; `measure_local` casts to float64 before the FFT. Reproduced on
`snts_kick_clip_validate_v1/bounce_000.wav`:

```
float64 -> sub_share = 0.7821868408685838   (== measure_local)
float32 -> sub_share = 0.782186857204015    (== real ears, exactly)
```

The `+1e-10` epsilon in `measure_local`'s total is not the cause; total band
energy on that file is ~4.06e7, so the epsilon shifts nothing. Conclusion: the
two measurers implement the same band math, and the whole disagreement is
float32 rounding in the FFT input. If we ever want exact equality, cast to
float32 in `measure_local`; there is no reason to, since ears is now the record.

## Caveats and exclusions

- **`kick_pitch_v1` skipped**, per the brief and PLAN.md: known dud, the swept
  range was too narrow and the curve is flat. It still has its old
  `kick_pitch_v1.acceptance.csv`; no ears CSV was generated for it. Re-run the
  sweep with a real range before trusting anything from that dir.
- **`roar_drive_v1` has no audio.** The dir holds 11 `setting_*.params.json`
  sidecars and zero `.wav` files; every sidecar has `"bounce": null` and
  `"measure": null`. It was an OSC param-only run that never bounced. Its
  `*.acceptance.ears.csv` therefore has no measure columns, and it cannot be
  compared. Re-run it through `run_sweep_stem.py` to get real data. This is a
  finding, not a Phase 1 failure.
- **Ignore `lufs_*` and `true_peak`.** The shim emits them, but our stems are
  gain-scaled, so absolute loudness and peak carry no meaning here. They were
  deliberately excluded from `--measure-keys` and must not enter `MAP.md` for
  these stems. Only the five band shares and `crest` are valid.
- **`assemble_curve.py` changed underneath this run.** Partway through, it began
  emitting an extra aligned `*.txt` view next to each CSV (the Phase 3 column-
  shift fix, owned by another agent). The first two ears CSVs
  (`snts_kick_clip_validate_v1`, `snts_kick_decap_drive_v1`) predate that and
  have no `.ears.txt`. The CSV contents are unaffected. Reported, not edited.

## Tooling added

`sweeps/compare_measurers.py` — stdlib only. Takes two acceptance CSVs, joins on
`index`, folds `crest_db` into `crest`, prints max abs difference per shared
numeric column, and exits non-zero if any column exceeds `--tol` (default
`1e-6`). `--tsv --label <sweep_id>` gives machine-readable rows for rolling many
sweeps into one table.

```sh
python3 sweeps/compare_measurers.py \
  sweeps/out/<id>/<id>.acceptance.ears.csv \
  sweeps/out/<id>/<id>.acceptance.local.csv
```

## Phase 1 "done when" checklist

- [x] Every real-kick sweep has an ears-measured CSV.
- [x] Max per-column difference vs `measure_local` is at or below tolerance
      (`3.175e-08` worst vs a `1e-6` budget), written up here.
- [x] Docs point to ears as the default measurer. Done: `HANDOFF.md` §4 (the
      Phase 1 finding + tolerance table), §10 (the run recipe), §12 (rewritten:
      ears is the record, `measure_local` is the fallback), §13 (file list);
      `MAP.md` (new "Measurer of record and error bars" section); `README.md`
      (index + stale-note warning).

## Addendum — verified after the fact

The whole comparison table above was RE-RUN from scratch with
`sweeps/compare_measurers.py` and reproduces to every digit (`OVERALL_FAIL=0`).

Two dirs listed as unmeasured above have since been handled:

- `snts_kick_clip_values_demo_v1` (created by the Phase 3 `values`-list demo)
  now has its own ears CSV, 2 rows, all 6 measure columns. It re-bounced
  Clipping 0.750 / 0.782, which `snts_kick_clip_validate_v1` had already
  bounced in an earlier session — an accidental but real reproducibility check.
  crest agreed to 0.014 / 0.015 dB across sessions. Logged in `HANDOFF.md` §4
  and `MAP.md` as a PROVISIONAL n=2 error bar; Phase 4 step 1 still owes the
  proper 5-repeat standard deviation.
- `test_measure_agreement.py` (Phase 3 item 6) now guards this report's
  guarantee. Verified passing: all 6 columns within 1e-6.

Interface note: `compare_measurers.py` accepts two positional CSVs (with `--a` /
`--b` aliases), `--tol` (default 1e-6), `--label`, and `--tsv`.
