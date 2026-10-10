# hands — Live control as a library

`hands` turns intent into changes in Ableton Live 12 and audio out of it. It is a library first
(the voice loop's skills call it: set knobs in the open set, export a short loop, pack probes into
one render) and a CLI for shells, skills and Hammerspoon.

Everything that touches Live goes through two channels: the LOM, over the AbletonLiveMCP Remote
Script on 127.0.0.1:16619 (`hands.live.transport`), and the GUI, over AppleScript, only for what
the LOM cannot do: time edits, saving, the Export dialog (`hands.live.ui`). Each Live step is
guarded: before and after it, `session.check` makes sure no dialog is open, one of our sets is in
front and the LOM answers, and stops the run on anything else.

## Modules

| Module | Public API |
|---|---|
| `live/transport.py` | `LiveClient(host, port, timeout=15, retries=2)`: `.run(code) -> result` (raises `LiveError`), `.execute(code) -> McpResult` (keeps `warning`, `elapsed`, `traceback`), `.ping() -> seconds`. `McpTransport`, `DryRunTransport`, `MockTransport`. Retries only while connecting: a sent request is never resent. |
| `live/ui.py` | `osa`, `osa_file` (rerun through Hammerspoon without an Accessibility grant), `menu`, `menu_enabled`, `front_title`, `windows`, `dialogs`, `close_dialogs`, `reap_modals`, `park_cursor` |
| `live/session.py` | `Guard`, `stop`, `check(client, where, *, expect_front=None, ours=True) -> str`, `open_set(client, name, *, save_current=True, timeout_s=120) -> float`, `save(name=None) -> bool`, `copy_set`, `launch`, `restart`, `audio_clock_ok`, `memory`, `other_agent_active` |
| `live/timeops.py` | `select(client, start, length)` (one LOM call + Edit > Select Loop), `delete`, `duplicate(…, end=None, clips_from=None)`, `copy`, `paste`, each checked by where the song ends |
| `live/knobs.py` | `Knob(track, device, param)` with `.id` / `Knob.parse`; `set_many(client, {knob: value})` (one write call), `read_many(client, knobs) -> {knob: Reading}` (a separate call), `apply(client, values, *, verify=True, tol=1e-4)`; `UNITS`, the measured .als-to-LOM conversions |
| `live/render.py` | `export(client, out, start_beat=None, length_beats=None, *, mode="Main", bits=32, sample_rate=44100) -> [Path]`, the one export path (`export_audio.applescript`) |
| `live/record.py` | `record_arrangement` (writes `<take>.timing.json`), `record_via_resampling`: real-time takes |
| `audio.py` | `check_audio(path, *, seconds)` (readable, finite, the right length, not silent), `slice_render`, `trim_take`, `best_lag`, `low_band`, `timeline_check` |
| `als.py` | the .als editor: `load`/`save`, `resolve`, `current_value`, `param_range`, `set_manual`, `set_speaker`, `rename_track`, `set_steps`, `add_device_from_donor`, `check -> Report`, `xml_hash` (plan-cache key) |
| `probe_kit.py` | `Kit`, `template`, `write_batch(kit, tag, steps, devices=())`, `render(client, batch_set, kit, out_dir)`, `merge_patterns`, `constant`, `scale`/`unscale` |
| `arrange/` | `fx` (clip edits, tracks as arguments), `autostate` (automation state, `restore` after Delete Time), `hats` (layered hat sections) |
| `steps.py` | `report(caption, level="minor", x=None, y=None)` to the studio app; `timing(step, seconds, **fields)` to `bench.jsonl` |
| `config.py` | `rig()`: the private rig settings below |
| `models.py`, `codegen.py`, `builder.py`, `runner.py` | `ProjectConfig` → LOM steps → `StepRunner` (`hands build / execute`); `models.py` is the source of the `lib/contracts` schemas (`scripts/gen_schemas.py`) |
| `ab.py` | A/B against "REF …" tracks and the master Spectrum (Hammerspoon hotkeys) |

A render, as the voice loop will run it:

```python
from hands import audio, config
from hands.live import knobs, render, session
from hands.live.knobs import Knob
from hands.live.transport import LiveClient

live = LiveClient()
session.check(live, "plan:start")
knobs.apply(live, {Knob("12-2022-06-02-001 [2026-05-25 092256]", ("StereoGain", 0), "Gain"): 0.96})
out = config.rig().renders_dir / "plan-0001.wav"
render.export(live, out, start_beat=8, length_beats=32)
audio.check_audio(out, seconds=32 * 60 / 160)
```

Knob values are in the .als's units (the parameter's Manual), the same everywhere: plans, probe
kits, readings. `knobs.UNITS` converts to the LOM's units and only holds conversions measured on
real devices; a knob without one is refused rather than guessed.

## Rig settings

What differs per Mac stays out of the repo. Each key comes from its environment variable, else
from `~/.config/zpkt/rig.toml` (or the file `ZPKT_RIG_CONFIG` names), else a neutral default.
Unknown keys are refused.

| Key | Environment | Default | Used for |
|---|---|---|---|
| `live_app` | `ZPKT_LIVE_APP` | `Ableton Live 12 Suite` | `open -a`, quit, restart |
| `sets_dir` | `ZPKT_SETS_DIR` | `~/Music/zpkt/sets` | the Live sets hands opens, copies and saves (named without `.als`) |
| `data_dir` | `ZPKT_DATA_DIR` | `~/Music/zpkt/data` | probe kits (`kits/`), batch renders, `bench.jsonl` |
| `renders_dir` | `ZPKT_RENDERS_DIR` | `~/Music/zpkt/renders` | where `hands live export NAME` writes a bare file name |
| `set_prefixes` | `ZPKT_SET_PREFIXES` (comma-separated) | `["zpkt_"]` | sets the guards accept as ours; new kit and batch sets get the first |
| `live_prefs_dir` | `ZPKT_LIVE_PREFS_DIR` | the newest `~/Library/Preferences/Ableton/Live *` | `Log.txt`, for `other_agent_active` |

```toml
# ~/.config/zpkt/rig.toml (an example; use your own folders and prefixes)
sets_dir = "~/Music/MyProject"
data_dir = "~/Music/MyProject/probe-data"
set_prefixes = ["MyProject_pp_", "MyProject_v_"]
```

The studio app's step reports use `STUDIO_STEP_URL` and `STUDIO_STEP_TOKEN` from the environment
(loopback only); without them `steps.report` does nothing.

## CLI

```bash
hands live ping                                  # is the Remote Script listening?
hands live exec --json "result = len(song.tracks)"   # LOM code (also --file, --stdin)
hands live check [--expect SET] [--any-set]      # the session guard
hands live export take.wav [--start 8 --length 32] [--mode Main] [--bits 24]
hands live modals [--reap]                       # Live's modal dialogs; --reap presses only safe buttons
hands als check FILE.als [--against SRC.als]     # offline self-checks before Live loads a set
hands als params FILE.als TRACK DEVICE_TAG
hands kit template KIT SRC KEEP_START KEEP_END P [--lead 8]
hands kit render BATCH_SET KIT [--out DIR]
hands record --arrangement --beats 80 --output take.wav
hands build --config project.json                # ProjectConfig → steps (dry run)
hands ab toggle | next | status;  hands spectrum
```

## Batch scripts

`scripts/probe_pack/` holds the HW002 batch-8 experiments that run on the library: `sweep8.py`
(sweeps and A/B batches in mix/solo/rest views), `ab_live.py` (experiments; source sets for kits)
and `climb_live.py` (the batch 6 hill climber, whose bests are batch 8's baseline). The pipeline is
in `../docs/hw002/batch-8-chord-and-break.md`; the measurements behind probe packing are in
`docs/probe-packing-findings.md`. `archive/` keeps the older batch, bench and sweep scripts for
reference; they no longer run.

## In zpkt

- The headless rig startup is `../lib/rig/start_headless.sh`.
- Agent skills for driving Live are in `skills/` and `.cursor/skills/ableton-guide` (the LOM crash
  rules); Hammerspoon macros in `macros/hammerspoon/`.
- The Letta/vibe stack (vibe server, its frontend, the MCP bridge for Letta) moved to
  `../prototypes/letta-vibe`.

## Tests

```bash
uv run pytest -q -p no:cacheprovider
```

Everything runs offline: a fake Remote Script on a free port, fakes for osascript and the GUI, the
BSD fixture set in `tests/fixtures` with devices planted the way Live writes them, and synthetic
audio. Nothing in the tests talks to Live.
