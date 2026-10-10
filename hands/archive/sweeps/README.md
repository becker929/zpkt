# Device instrumentation sweeps (Stage-3 keystone)

The knob → measure map. Sweep one device parameter, bounce each setting, hand
the `{wav, params.json}` pairs to the lab (`ears`), record which knob moves which
measure by how much.

## The seam (file contract)

- **In (research → Ableton):** a `*.sweep.json` spec — which device+parameter to
  sweep, over what range/resolution, on which instrument. See
  `kick_pitch.sweep.json`.
- **Out (Ableton → research):** a directory of pairs, one per setting:
  - `bounce_NNN.wav` — isolated audio bounce
  - `bounce_NNN.params.json` — the exact parameter state that produced it
    (`requested_value` and the read-back `true_value`, plus device_expr, unit,
    tempo/beats, predicted measure). A bounce without its params sidecar is a
    dead row, so the driver always writes them together.

The lab consumes the pair out-of-band, e.g. `ears analyze bounce_NNN.wav --json`.
The `ears` project is not in this repo — the working lab lives at
`/Users/anthonybecker/_agent_scratch/ears_lab/` (with a `.venv` and a shim).
See `HANDOFF.md` §12 for the exact `--ears-cmd`.

## Read these first

| File | What it tells you |
|---|---|
| `PLAN.md` | The five-phase tidy-first work plan. The order is not optional. |
| `STATUS.md` | Which phases are done and which are not. |
| `HANDOFF.md` | Current truth: findings (§4), how to drive Live (§7), the measurer (§12). |
| `MAP.md` | The knob → measure map itself, with inverse lookups. |
| `PHASE1_REPORT.md` | Proof that real `ears` and `measure_local` agree. |

Everything below this line is a historical snapshot from earlier turns. Where it
conflicts with `HANDOFF.md`, `HANDOFF.md` wins. In particular: the real `ears`
lab **is** runnable now (the note below saying otherwise is stale), and
`run_sweep_stem.py` — not `run_sweep.py` or `run_sweep_osc.py` — is the runner
to use.

## Two paths

| | Path A (OSC) | Path B (LOM/MCP) |
|---|---|---|
| Runner | `run_sweep_osc.py` | `run_sweep.py` |
| Reaches | top-level track device params | any param incl. nested drum-pad-chain devices |
| Can bounce? | **no** (AbletonOSC has no render) | yes (`recorder.record_via_resampling`) |
| Needs | AbletonOSC control surface (up) | AbletonMCP Remote Script on :16619 (not installed here) |

Path A proves + read-back-verifies the **parameter axis** on a running set today.
Path B additionally bounces isolated audio so the lab can fill the measure.

## Files

| File | Role |
|---|---|
| `base_kick.py` | The static one-instrument `ProjectConfig` (Drum Rack + one Simpler kick + 4-on-4 MIDI). `--dump-json` emits `base_kick.json`. |
| `base_kick.json` | Generated; feed to `hands build --config`. |
| `kick_pitch.sweep.json` | Path-B seam spec: sweep Simpler `Transpose` (pitch) → predicted `sub_share`. |
| `run_sweep.py` | Path-B driver: build once, then set → read-back → bounce → sidecar, per value. Resumable. |
| `roar_drive.sweep.json` | Path-A seam spec: sweep `Roar Drive` on the kick group → predicted `crest`. |
| `run_sweep_osc.py` | Path-A runner: capture → (set → read-back → sidecar)* → restore, over OSC. No bounce. |
| `out/roar_drive_v1/` | Live-verified result of the Path-A sweep (11 sidecars + curve CSV). |

## Update 2026-09-08 (turn 2)

Path B is now ENABLED and the full loop is proven on a set BUILT from
plugins (not a real saved set). See `HANDOFF.md` for the current truth.
Use `run_sweep_stem.py` (isolated-stem bounce) — it works here; the
resampling recorder bounced silence until fixes/workarounds. The
findings below are the earlier (turn 1) snapshot.

## Environment findings (verified 2026-09-08, turn 1)

Against the running Live 12.4.5 set (Anthony's hard-techno session, 18 tracks:
`kick group`, `kick`, `rumble`, `perc group`, …):

- **Path A (OSC) is up** and can set + read back top-level device parameters.
  Verified end-to-end: swept `kick group / Roar / Drive` 0.0→1.0 in 11 steps;
  read-back was exact and the dB mapping clean/monotonic (−24 dB → +24 dB);
  the original value (5.0 dB) was restored. See `out/roar_drive_v1/`.
- **Path B (LOM/MCP) is DOWN.** The AbletonMCP Remote Script that serves TCP
  :16619 was **not installed**; `hands ableton-mcp` (:9010) is only a Letta HTTP
  proxy *in front of* :16619, not the socket itself. The opendining remote
  script (`opendining/ableton-mcp-server@v0.1.1`, verified to inject the globals
  `hands` needs: `load_to`, `find_item`, `MidiNoteSpecification`, `browser`,
  `time`) is now **staged** at
  `~/Music/Ableton/User Library/Remote Scripts/AbletonLiveMCP/__init__.py`.
  It is **not yet enabled** — enabling needs Settings → Link/Tempo/MIDI →
  Control Surface → `AbletonLiveMCP` (In/Out: None) **and a Live restart**
  (rescan). The running session is `Untitled` (unsaved), so **save first**,
  then restart + enable, then `nc -z 127.0.0.1 16619` should pass.
- **osascript bounce WORKS (no Path B needed) — with one rule: never reuse a
  filename.** The native-export driver (`export_audio.applescript`) run
  off-screen on a virtual display produced a real WAV
  (`/tmp/hands_bounce_nz9q7.wav`, 44.1 kHz stereo). The earlier failure was the
  "replace existing?" sheet wedging the flow; a guaranteed-unique output name
  avoids it entirely. `run_sweep_osc.py --bounce` now renders one unique WAV per
  setting via this path, so the full audio loop needs **no MCP bridge**. Caveat:
  it renders the master ("Main") mix — solo the source track for an isolated stem.
- **The lab (`ears`) is not runnable here**: only stale copies under
  `~/Archives/…` exist; no `ears` CLI on PATH. So the `measure` column stays
  `null` until a bounce is handed to a live `ears`.

Net: **both halves of the loop now work over Path A alone** — parameter
control (OSC set + read-back) and audio bounce (native export with unique
filenames), no MCP bridge required. The only remaining out-of-band piece is
measurement (`ears`), which is decoupled by design (§6 seam) and not runnable
in this checkout. Path B (the now-staged `AbletonLiveMCP` remote script) is
still the better route for *nested* params (drum-pad Simpler) and headless
resampling bounce; enable it after saving + restarting Live.

To run the full Path-A loop when a real instrument set is loaded:
`run_sweep_osc.py --bounce` with Live on a virtual display, then
`assemble_curve.py --dir out/<sweep_id> --ears-cmd ... --measure-keys ...`.

## Run

```bash
# Path A (works now): sweep a top-level device param over OSC, with restore
uv run python sweeps/run_sweep_osc.py --sweep sweeps/roar_drive.sweep.json

# Path B below (needs the AbletonMCP Remote Script on :16619 first)

# 1. validate offline (no Ableton, no MCP bridge needed)
uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --build --dry-run

# 2. bring up Path B (the MCP bridge on 127.0.0.1:16619) first, then:
uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --build

# 3. crash mid-run? rerun — finished (wav+sidecar) rows are skipped:
uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --resume-from 6
```

## Why the sweep is a driver, not a ProjectConfig field

`ProjectConfig` is a declarative snapshot of ONE project state; it has no
parameter-trajectory primitive. The sweep is therefore a loop *around* a base
config: build the instrument once, then step the knob via LOM and bounce each
setting. This keeps the config schema untouched and the sweep spec decoupled.

## Acceptance (the spike's milestone)

One clean CSV/JSON series `{param value → measure}` that is monotonic and matches
(or cleanly falsifies) one predicted mapping. That single curve = Ableton access
proven, loop closed. Assemble it from the sidecars + lab output.

## Crash-avoidance compliance (Path B rules)

- Set and read-back are **separate** `execute()` calls (Rule 1: no post-set readback).
- Each snippet touches one device, no parameter sweeps-within-a-call (Rule 2).
- No long sleeps inside a call; `settle_seconds` waits happen in the driver, between calls (Rule 7).
