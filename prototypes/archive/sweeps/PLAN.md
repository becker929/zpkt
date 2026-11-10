# Tidy-first plan (before climbing the ladder)

This is the work plan for the knob->measure map. The rule is simple: tidy the
foundation first, then climb. We do NOT start the Critic / Assistant / Engineer
rungs until the five phases below are done.

Phases run in this order. Do not skip ahead. Each phase has a goal, the steps,
and a clear "done when" test. Finish a phase before starting the next.

Order:
1. Redo everything with the ears lab.
2. Housekeeping and provenance.
3. Tooling and robustness.
4. Validate and harden the map as a control.
5. Widen the map.

---

## Where things are (facts you need)

- Sweep code + data: `~/sandbox/autodaw/hands/sweeps/`.
- Runner (the good one): `run_sweep_stem.py`. Others (`run_sweep.py`,
  `run_sweep_osc.py`) are older and flaky. Ignore them for now.
- Measurer today: `measure_local.py` (provisional). Emits `crest_db` and
  canonical band shares.
- Curve builder: `assemble_curve.py`. Joins bounces + a measurer into an
  acceptance CSV.
- The map: `MAP.md`. The log: `HANDOFF.md` (append findings to section 4).
- Real lab: `/Users/anthonybecker/_agent_scratch/ears_lab/` with a working
  `.venv` and a shim `ears_shim.py`.
- ears run line: `.venv/bin/ears analyze <wav> --json --no-embeddings`.
- ears via the pipeline:
  `--ears-cmd "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python /Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py"`.
- Live clone is open. Rig is up: capture track `STEM_CAP` = `song.tracks[44]`,
  session clip on `song.tracks[6].clip_slots[0]`. Kick (G) = `song.tracks[6]`.

Existing data folders under `out/`:
- Real SNTS kick: `snts_kick_decap_drive_v1`, `snts_kick_decap_drive_fine_v2`,
  `snts_kick_clip_thresh_v1`, `snts_kick_clip_validate_v1`,
  `snts_kick_transient_attack_v1`.
- Synthetic (older, plugin test kick): `kick_pitch_v1`, `kick_pitch_wide_v1`,
  `roar_drive_v1`. `kick_pitch_v1` was a bad range (flat) and is a known dud.

Ground truth we already proved: on one bounce, ears `band_energy.sub` matched
`measure_local` `sub_share` to 7 decimals, and crest matched exactly. So we
expect a full re-measure to agree. This phase is about proving that everywhere,
not discovering a difference.

---

## Phase 1 -- Redo everything with the ears lab

Goal: make the real `ears` lab the one measurer of record. Re-measure every
sweep with ears, confirm it matches `measure_local`, then make ears the
default. Keep `measure_local` only as a documented fallback.

Why: right now two measurers exist. We proved they agree on one file. We must
prove it on all files, then stop depending on the provisional one.

Steps:
1. Sanity-run ears once by hand on a known bounce to confirm the venv still
   works: `.venv/bin/ears analyze .../snts_kick_clip_validate_v1/bounce_000.wav
   --json --no-embeddings`. Expect the loudness + band_energy JSON.
2. Re-assemble EACH real-kick sweep with the ears shim into a NEW file so we
   never overwrite the old CSV. Use a distinct name, e.g.
   `<sweep_id>.acceptance.ears.csv`, via `--out` if supported, else assemble
   into a temp dir and copy. Measure keys: `crest sub_share low_share mid_share
   high_share air_share`.
3. Diff the ears CSV against the existing `measure_local` CSV column by column.
   Write a tiny compare step (Python or `paste`+`awk`) that prints the max
   absolute difference per column.
4. Decide the tolerance: band shares should match to ~1e-6 (same math). crest
   is computed by the shim with the same formula, so it should match to ~1e-6
   too. Flag any column that drifts more than that.
5. Re-measure the synthetic sweeps too (`kick_pitch_wide_v1`, `roar_drive_v1`)
   for completeness. Skip the known dud `kick_pitch_v1` (bad range) but note it.
6. Once all diffs pass, set ears as the default in our docs: update the
   `assemble_curve.py` usage examples in `HANDOFF.md` and the skill to the ears
   `--ears-cmd`. Keep `measure_local` documented as the offline fallback.

Done when:
- Every real-kick sweep has an ears-measured CSV.
- Max per-column difference vs `measure_local` is at or below tolerance,
  written into `HANDOFF.md`.
- The docs point to ears as the default measurer.

Risks / notes:
- ears' `lufs`/`true_peak` are gain-dependent. They are meaningless on our
  gain-scaled stems. Do NOT add them to the map for these stems. Only band
  shares + crest are valid here.
- If ears and `measure_local` disagree beyond tolerance, STOP. That is a real
  finding; investigate before making ears default.

---

## Phase 2 -- Housekeeping and provenance

Goal: make the work reproducible and safe to leave. Anyone should be able to
re-open the clone, see what changed, and trust the data.

Why: we have been editing a live clone by hand. We need a written, verifiable
record of the original state and how to rebuild the rig.

Steps:
1. Snapshot the clone's ORIGINAL device state to a JSON file in the repo, e.g.
   `snapshots/snts_kick_devices.json`. For track 6 record every device name,
   its `On` value, and the swept params' defaults (Decap Drive/Style, Clipping,
   Attack). This is the "restore target".
2. Write a one-paragraph "how to relaunch" recipe in `HANDOFF.md`: clone path,
   the `.als` to open, how to confirm Path B, and where the rig lives
   (`STEM_CAP` = track 44, session clip on track 6 slot 0).
3. Record the clone's provenance: which real `.als` it came from, the copy
   command used, and the clone path under `_agent_scratch`. Confirm the real
   file is untouched (it should be; we never saved).
4. Tag each sweep's provenance. Confirm every `out/<sweep_id>/` has its spec
   file and that each bounce has its `.params.json` sidecar. List any orphan
   wavs (wav without sidecar) and delete or re-measure them.
5. Add a short `README` header to the `sweeps/` folder (or extend `HANDOFF.md`)
   that lists every spec, its out dir, and one line on what it found. A simple
   index so nobody has to spelunk.
6. Decide the ears lab's home. It lives in `_agent_scratch`, which is
   disposable. Either (a) document the exact rebuild commands so it can be
   recreated, or (b) move it somewhere more permanent. Write down the choice.
7. Pin the ears environment: save the resolved versions (librosa, numpy,
   pyloudnorm, soundfile, typer, rich) into a `requirements.lock` or note them
   in `HANDOFF.md`, so the lab rebuilds the same way.

Done when:
- An original-state snapshot JSON exists and matches current restored state.
- A relaunch + rig-rebuild recipe is written.
- Every out dir is spec-linked and sidecar-complete; no orphans.
- The ears lab rebuild is documented and version-pinned.

Risks / notes:
- Never save the real `.als`. Snapshots read state; they do not write it.
- `_agent_scratch` can be wiped. Anything we must keep goes in the repo.

---

## Phase 3 -- Tooling and robustness

Goal: make the pipeline hard to misuse and easy to trust. Fix the sharp edges
we hit by hand.

Why: we hit three papercuts: the blank `value_string` column shift, no
explicit value lists, and no guard against silent bounces.

Steps:
1. Explicit value list in the spec. Add an optional `values` array to the sweep
   spec. If present, `run_sweep_stem.py` and `assemble_curve.py` use it
   verbatim instead of start/stop/steps. This lets us validate exact inverse-
   table points in one run.
2. Fix the column-shift gotcha. In `assemble_curve.py`, when `value_string` is
   blank (VST), do not let a plain `column -t` misalign. Either always quote
   the CSV, or emit a second "wide" view with headers that stay aligned. Add a
   note so future reads are safe.
3. Silent-bounce guard. In `run_sweep_stem.py`, fail fast if a bounce wav is
   under a threshold size (e.g. < 50 KB) or its peak is near silence. A silent
   bounce means the rig is wrong; do not write a dead row.
4. Auto-summary of a curve. Add a small helper that reads an acceptance CSV and
   prints: direction (up/down), monotonic or humped, the extrema and where they
   sit, and any invertible region. This replaces hand-reading each curve.
5. One-command rig setup/teardown. Script the "enable target device, disable
   the others, restore afterward" dance for track 6, so we stop toggling
   devices by hand each sweep. Include a `--restore` that puts the snapshot
   back.
6. Small regression test. A test that runs ears + `measure_local` on one fixed
   bounce and fails if band shares diverge beyond tolerance. Guards the Phase 1
   guarantee going forward.

Done when:
- A spec with an explicit `values` list runs end to end.
- Reading any acceptance CSV cannot silently misalign columns.
- A silent bounce aborts the run with a clear message.
- The curve auto-summary and the rig setup/teardown scripts exist and work.
- The ears-vs-local regression test passes.

Risks / notes:
- Keep the file contract stable. The IN spec and the OUT
  wav+`.params.json` pair must not change shape. Add fields; do not rename.
- Make each tool change small and tested on one existing sweep before trusting
  it broadly.

---

## Phase 4 -- Validate and harden the map as a control

Goal: prove the map predicts real knob moves across its whole usable range, not
just the three points we already checked. Add error bars.

Why: the map is only useful to the Assistant if "target measure -> knob value"
lands within a known tolerance. We validated the clipper mid-region once. That
is a start, not proof.

Steps:
1. Measure crest noise honestly. Bounce ONE fixed clipper setting 5 times.
   Compute the run-to-run standard deviation of crest. Write it in `MAP.md` as
   the error bar on every crest prediction. Use the explicit `values` list from
   Phase 3.
2. Validate the clipper floor and ceiling rows we skipped (target crest 4.5,
   8.0, 8.5 dB). Confirm where the table clamps. Mark saturating rows clearly so
   the Assistant never asks for an impossible crest.
3. Validate the Transient Attack inverse in its clean 0.5..0.9 region. Pick a
   target crest (e.g. 12 dB), read off the predicted Attack, bounce, and check
   within the noise band.
4. Test whether two knobs compose. Set Attack for a target crest, then set the
   clipper for a second target, and confirm each still lands. If they interfere,
   record the coupling; that shapes the Assistant's order of operations.
5. Test map portability. Re-run the clipper validation with Decapitator left ON
   (a more realistic chain) and see if the table still holds or shifts.
6. Fine-sweep the Attack 0.5..0.9 region at 0.025 resolution to confirm the
   crest peak location (the coarse sweep put it at 0.9; that may be an artifact,
   like the Decap hump was).

Done when:
- `MAP.md` lists a measured crest error bar.
- Clipper floor/ceiling behavior is validated and labeled.
- The Attack inverse is validated in its clean region.
- Two-knob composition and Decap-on portability are tested and logged.

Risks / notes:
- Always restore device On-states and swept params after each test.
- If a prediction misses badly, that is a finding, not a failure. Log the miss
  and the conditions.

---

## Phase 5 -- Widen the map

Goal: add more knobs and a second instrument, so the map is not all-kick and
not all-clipper. Build toward an orthogonality matrix.

Why: the Assistant needs choices. It should pick the knob that moves the target
measure while disturbing the others least.

Steps:
1. Add the mirror knob: sweep Transient Sustain (`devices[3]` param 3). Predict
   it lowers crest, the opposite of Attack. Confirm and log.
2. Add a spectral lever: sweep an EQ Eight band gain or the HPF against
   `sub_share` / `low_share`. A clean, near-orthogonal spectral control.
3. Add a second Decap axis: sweep Decap Style (fixed at 0.5 so far). It likely
   reshapes the whole Drive curve.
4. Move to a SECOND real instrument. Pick another standalone track (a pitched
   hat, a snare/clap, or a bass) from Anthony's library. Repeat the full
   pipeline: clone, locate, rig, sweep, measure, log.
5. Re-test the pitch reversal on real audio. On a real instrument with a
   tuning/pitch knob, re-check the sampled-kick `pitch -> sub_share` reversal we
   saw on the synthetic kick.
6. Build the orthogonality matrix. For every mapped knob, record which measures
   move and which stay put (crest / sub / low / mid / high / air). This table is
   the direct input to the Assistant rung.

Done when:
- At least two more kick knobs are mapped (Sustain + one spectral).
- A second real instrument has at least one mapped knob.
- An orthogonality matrix exists in `MAP.md`.

Risks / notes:
- Same rules: COW clone only, sweep the WHOLE range, pick ranges that cross the
  band edge you measure, restore everything.
- For a group/bus track, the tap sums siblings. Prefer standalone tracks first.

---

## After all five phases (not before): climb the ladder

Only once phases 1-5 are done do we start Critic -> Assistant -> Engineer:
build a reference corpus (Critic), write "gap -> knob move" using the map +
orthogonality matrix (Assistant), then close the render/measure/adjust loop
(Engineer). That work gets its own plan. Do not begin it early.

## Global safety rules (every phase)

- Work only on the COW clone under `_agent_scratch`. Never save the real file.
- Restore every device On-state and param you flip. Verify by read-back.
- Prepend commands with `timeout` so nothing wedges.
- Append findings to `HANDOFF.md` section 4. Add a `MAP.md` row per new knob.
- Keep the file contract stable: IN `*.sweep.json`, OUT wav + `.params.json`.
