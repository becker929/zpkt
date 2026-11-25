# zpkt.live: drive Ableton Live

`zpkt.live` (until 24 Nov 2026 the `hands` package; `hands` still works as a command and an import) turns intent into changes in Ableton Live 12 and audio out of it. It is a library first
(set knobs in the open set, export a short loop, pack several variants into one render) and a CLI
for shells, agents and hotkeys.

New here? [`docs/getting-started.md`](../../../docs/getting-started.md) installs the Remote Script and
gets you to a first export.

Everything that touches Live goes through two channels: the LOM, over the AbletonLiveMCP Remote
Script on 127.0.0.1:16619 (`zpkt.live.transport`), and the GUI, over AppleScript, only for what
the LOM cannot do: time edits, saving, the Export dialog (`zpkt.live.ui`). Each Live step is
guarded: before and after it, `session.check` makes sure no dialog is open, one of our sets is in
front and the LOM answers, and stops the run on anything else.

## Common asks, one command each

Look here before writing LOM code or reading a module. If an ask is missing and took more than one command, add
the command and a row.

| Ask | Command |
|---|---|
| Is Live there, which set is in front? | `hands live check` |
| Open a set (saving the one in front) | `hands live open NAME` (`--no-save` discards it: answers Don't Save) |
| Load a set from its file again, even the one in front (discards unsaved changes) | `hands live reopen [NAME]` |
| What mix does a saved set hold? What differs between two saved sets? | `hands als mix FILE [--against OTHER]` (offline, Live untouched) |
| Save the set (an explicit save, not Live's backup) | `hands live save [--as NAME] [--state NAME]` |
| Keep the whole mix (every fader, send, mute, device value) | `hands live state take NAME` (about 3 s) |
| What changed since then? / Does Live match a recipe? | `hands live state diff NAME [OTHER]` (a recipe .json with a `"desk"` works) |
| Put a kept mix (or a recipe's desk) back | `hands live state put NAME [--only TRACK]` |
| Which mixes are kept for this set? | `hands live state ls` |
| What is this value: its range, unit, steps, default? | `hands live describe "TRACK/DEVICE/PARAM" ...` (state keys; one call for up to 32) |
| What is selected in Live? | `hands live selection` (track, device and parameter as a state key) |
| Will this page of controls work, and how does it land on the MiniLab? | `hands live page lint PAGE.json` (`zpkt.live.page`; contract `lib/contracts/page.schema.json`) |
| What changed between two mixes, and who moved it? | `zpkt.live.changes.between(a, b, who)`; one set's stream in `<sets_dir>/changes/<set>.jsonl` |
| Render a span to a file | `hands live export FILE --start BEAT --length BEATS` |
| Which output is Live playing through? / Play through another one | `hands rig output [NAME]` (e.g. `Yeti`) |
| Render many variants of a section in one export | `hands kit template ...`, then `hands kit render BATCH KIT` (probe kits: the fast batch-render method) |
| Try a sound with knobs to turn | `hands panel make --spec ...` (below) |
| A dialog is stuck | `hands live modals --reap` |
| Live is acting strange | `hands rig check`, then `hands rig reset` |

## Modules

| Module | Public API |
|---|---|
| `transport.py` | `LiveClient(host, port=None, timeout=15, retries=2)` (no port: the rig's `live_port`): `.run(code) -> result` (raises `LiveError`), `.execute(code) -> McpResult` (keeps `warning`, `elapsed`, `traceback`), `.ping() -> seconds`. `McpTransport`, `DryRunTransport`, `MockTransport`. Retries only while connecting: a sent request is never resent. |
| `ui.py` | `osa`, `osa_file` (rerun through Hammerspoon without an Accessibility grant), `menu`, `menu_enabled`, `front_title`, `windows`, `dialogs`, `close_dialogs`, `reap_modals`, `park_cursor` |
| `session.py` | `Guard`, `stop`, `check(client, where, *, expect_front=None, ours=True) -> str`, `open_set`, `save(name=None) -> bool`, `copy_set`, `front_set() -> (name, guessed)`, `reload_set`, `launch`, `restart`, `audio_clock_ok`, `memory`, `other_agent_active` |
| `state.py` | the one model of the whole mix: `State` (typed; values are `ShownRaw` pairs `[shown, raw]`), `take(client, only=None)`, `diff(a, b, ignore=())`, `summarize`, `put(client, state, only=None)` (writes only what differs, reads back), `load`/`load_dict` (a state, or a mix desk recipe's `"desk"`, read through `desk.py`), `save`, `path_for` |
| `desk.py` | the mix desk recipe's `desk` as a contract (pydantic; `lib/contracts/desk.schema.json` is generated from it) and `parse` |
| `inlive/` | rules that also run inside Live (stdlib, Python 3.11, loadable by path, or sent as source with `with_source`): `tracks` (a track by name: Main, returns without their letter), `shown` (the raw value that shows as "-6 dB"), `keys` (state keys and the three spellings of a send) |
| `writes.py` | `set_raw(client, device, [(name, raw)])` and `read_raw`: device parameters a few to a call |
| `knobs.py`, `units.py` | `Knob(track, device, param)`: `.id` (`track/Tag#i/param`), `.pipe_id` (`track\|Tag:i\|param`), `Knob.parse` (both); `set_many`, `read_many`, `apply(client, values, *, verify=True)`; `units.UNITS`, the measured .als-to-LOM conversions |
| `export.py` | `export(client, out, start, length, *, method="keys"\|"menu", staging=None, ...)`: both ways through the Export dialog; `export_by_menu` (no keystrokes, Main), `save_as(folder, name, *, project=True)`, `SavePanel(reach="where_popup"\|"go_to_folder")` |
| `render.py` | `export(...)`, the keystroke method (`export_audio.applescript`) |
| `ops.py` | `LiveOps(client, staging=None, save_panel=SavePanel())`: `run`, `guard`, `setp` and `mixer` in shown units, `params`, `load_item`, `select_track`, `devices`, `export`, `save_as`, for scripts that build and render sets (the arranger, the mix desk; outside zpkt, the music bot's booth) |
| `timeops.py` | `select(client, start, length)`, `delete`, `duplicate`, `copy`, `paste`, each checked by where the song ends |
| `record.py` | `record_arrangement` (writes `<take>.timing.json`), `record_via_resampling`: real-time takes |
| `panel.py` (+ `riff`, `panel_render`, `panel_blocks`, `mix`, `versions`, `song`) | `hands panel` and `hands song`: instrument and mix panels, grids of versions, songs over sections; `panel_blocks` prints what Zpkt web reads |
| `rig.py`, `hold.py` | `hands rig check/reset`; the one lock on Live and the notes that put an interrupted command's changes back |
| `audio.py` | `check_audio(path, *, seconds)`, `slice_render`, `trim_take`, `best_lag`, `low_band`, `timeline_check` |
| `als/` | the .als offline: `file.py` (load/save, `resolve`, `current_value`, `set_manual`, `set_steps`, `add_device_from_donor`, `xml_hash`), `check.py` (`check -> Report`, `list_params`), `mix.py` (`mix_state`, `mix_lines`); all as `zpkt.live.als.<name>` |
| `probe_kit.py` | probe kits (`hands kit`): `Kit`, `template`, `write_batch`, `render`, `merge_patterns`, `constant`, `scale`/`unscale`. Many variants of a section in one load and one export: the fast batch-render method |
| `arrange/` | `fx` (clip edits), `autostate` (automation state, `restore` after Delete Time), `hats` |
| `library/` | the WIP library, read-only: `inventory(...)` scores each track's seven steps (`contrib/docs/workflow.md`) |
| `bench.py`, `config.py` | `timing(step, seconds, **fields)` to `<data_dir>/bench.jsonl`; `rig()`, the settings below |
| `models.py`, `codegen.py`, `builder.py`, `runner.py` | the first design: `ProjectConfig` → LOM steps → `StepRunner` (`hands build / execute`). Its user, `prototypes/engineer`, was removed on 24 Nov 2026; I keep it for now to see whether it folds into something. `models.py` is the source of two `lib/contracts` schemas (`tools/gen_schemas.py`) |
| `ab.py` | A/B against "REF …" tracks and the master Spectrum (Hammerspoon hotkeys) |
| `testing/` | `FakeLive(song)`, an offline Live that runs the Remote Script's own code over a fake set; `fake_set(spec)`, `hw002_like()`, `MiniLab_3` ([README](testing/README.md)) |

Each CLI module (`cli.py`, `live_cli.py`, `state_cli.py`, `edit_cli.py`, `panel_cli.py`, `als_cli.py`,
`kit_cli.py`, `project_cli.py`) only parses arguments and prints; the work is in the modules above.

A render from Python:

```python
from zpkt.live import audio, config
from zpkt.live import knobs, render, session
from zpkt.live.knobs import Knob
from zpkt.live.transport import LiveClient

live = LiveClient()
session.check(live, "render:start")
knobs.apply(live, {Knob("12-2022-06-02-001 [2026-05-25 092256]", ("StereoGain", 0), "Gain"): 0.96})
out = config.rig().renders_dir / "take-0001.wav"
render.export(live, out, start_beat=8, length_beats=32)
audio.check_audio(out, seconds=32 * 60 / 160)
```

Knob values are in the .als's units (the parameter's Manual), as in probe kits and knob readings; the mix state,
panels and the mix desk use Live's raw values instead. `units.UNITS` converts to the LOM's units and only holds conversions measured on
real devices; a knob without one is refused rather than guessed.

## Module map

Every module of the old `hands` package is now `zpkt.live`'s, and `hands.live.*` is flattened into it. The old
names still import, and give the same module (`zpkt._aliases`):

| Old | New |
|---|---|
| `hands.<module>` (`hands.config`, `hands.als.file`, `hands.library.inventory`, `hands.testing.fakelive`, ...) | `zpkt.live.<module>` |
| `hands.live.<module>` (`hands.live.state`, `hands.live.transport`, `hands.live.inlive.tracks`, ...) | `zpkt.live.<module>` |
| `hands.live.cli` (`hands live ...`) | `zpkt.live.live_cli` (`hands.cli`, the whole `hands` command, stays `zpkt.live.cli`) |
| `hands/remote_scripts/` | `src/zpkt/live/remote_scripts/` |
| `hands/tests/` | `tests/live/` |
| `ears.<module>`, `ears.meters.<module>`, `mlab.<module>` | `zpkt.audio.<module>`, `zpkt.audio.meters.<module>` ([its README](../audio/README.md)) |

The commands keep their names: `hands` is `zpkt live`, `ears` is `zpkt audio`, and `mlab` stays.

## Rig settings

What differs per Mac stays out of the repo. With no file and no variables set, everything lives
under `~/Music/zpkt/`. Each key comes from its environment variable, else
from `~/.config/zpkt/rig.toml` (or the file `ZPKT_RIG_CONFIG` names), else a neutral default.
Unknown keys are refused; `plans_dir`, retired with `hands plan`, is still read and ignored.

| Key | Environment | Default | Used for |
|---|---|---|---|
| `live_app` | `ZPKT_LIVE_APP` | `Ableton Live 12 Suite` | `open -a`, quit, restart |
| `live_port` | `ZPKT_LIVE_PORT` | `16619` | the Remote Script's port, for every client and `--port` default; a test points it at a `FakeLive` |
| `sets_dir` | `ZPKT_SETS_DIR` | `~/Music/zpkt/sets` | the Live sets hands opens, copies and saves (named without `.als`); must be a Live Project folder |
| `data_dir` | `ZPKT_DATA_DIR` | `~/Music/zpkt/data` | probe kits (`kits/`), batch renders, `bench.jsonl` |
| `renders_dir` | `ZPKT_RENDERS_DIR` | `~/Music/zpkt/renders` | where `hands live export NAME` writes a bare file name |
| `set_prefixes` | `ZPKT_SET_PREFIXES` (comma-separated) | `["zpkt_"]` | sets the guards accept as ours; new kit and batch sets get the first |
| `live_prefs_dir` | `ZPKT_LIVE_PREFS_DIR` | the newest `~/Library/Preferences/Ableton/Live *` | `Log.txt`, for `other_agent_active` |
| `library_dir` | `ZPKT_LIBRARY_DIR` | `~/Music/zpkt/library` | work-in-progress Live projects, one folder per track, read-only (`hands library inventory`) |
| `records_file` | `ZPKT_RECORDS_FILE` | `<library_dir>/records.toml` | what you have declared done per track; it beats the inventory's guess (`contrib/docs/workflow.md`) |

```toml
# ~/.config/zpkt/rig.toml (an example; use your own folders and prefixes)
sets_dir = "~/Music/MyProject"
data_dir = "~/Music/MyProject/probe-data"
set_prefixes = ["MyProject_pp_", "MyProject_v_"]
```


## CLI

```bash
hands live ping                                  # is the Remote Script listening?
hands live exec --json "result = len(song.tracks)"   # LOM code (also --file, --stdin)
hands live check [--expect SET] [--any-set]      # the session guard
hands live save [--as NAME] [--state NAME]       # File > Save, wait for the file; a named copy; the mix state
hands live state take|diff|put|ls NAME           # the mix state as data (README "Common asks")
hands live describe KEY... | selection | page lint PAGE.json   # what the one interface's pages are built from
hands live reset|clip create|device load/set/list   # build a set from the shell; `hands live surface apply` guesses units
hands live export take.wav [--start 8 --length 32] [--mode Main] [--bits 24]
hands live modals [--reap]                       # Live's modal dialogs; --reap presses only safe buttons
hands als check FILE.als [--against SRC.als]     # offline self-checks before Live loads a set
hands als params FILE.als TRACK DEVICE_TAG
hands als mix FILE.als [--against OTHER.als]      # the mix a saved set holds; what differs between two
hands kit template KIT SRC KEEP_START KEEP_END P [--lead 8]
hands kit render BATCH_SET KIT [--out DIR]
hands record --arrangement --beats 80 --output take.wav
hands build --config project.json                # the first design: ProjectConfig → steps (dry run); execute runs them
hands library inventory [--root DIR] [--exports DIR] [--measure] [--json | --markdown]   # each WIP track's seven steps
hands ab toggle | next | status;  hands spectrum
```

### An instrument with its control panel: `hands panel`

One command per step, for an agent answering in Zpkt web (or anyone at a shell):

```bash
hands panel params Operator --grep 'wave|filter'     # names, ranges, what Live shows, choices (cached after the first read)
hands panel make --spec - <<'JSON'                    # track + instrument + values + riff + render + the blocks to paste
{"name": "funk-bass", "instrument": "Operator", "tempo": 104,
 "params": {"Osc-A Wave": "Saw D", "Filter Freq": "600 Hz", "Filter Res": "45 %"},
 "notes": [["A2", 0, 0.4, 115], ["C3", 1.5, 0.4, 105], ["E3", 3, 0.5, 110]], "beats": 8,
 "controls": [{"param": "Filter Freq", "label": "Cutoff"}, "Filter Res"]}
JSON
hands panel make --spec '{"sound": "saw", "seq": "A B C D", "every": 4}'   # the short form: no parameter names, name made up
hands panel apply funk-bass --state '{"values": {"filter_freq": 0.7}}'   # the page's values back in; next version + A/B deck
hands panel grid funk-bass --axes '{"cutoff": {"from": "200 Hz", "to": "2 kHz", "steps": 4}}'   # 4 versions in one deck, A B C D
hands panel pick funk-bass 1 C                         # keep version C of grid 1 (sets Live; nothing is rendered again)
hands panel make --spec '{"name": "buses", "bars": [17, 8], "faders": ["bus-kick", "bus-hats"]}'   # a mix panel: tracks in the set, bars of the arrangement
hands song make --spec '{"name": "tune", "tempo": 124, "sections": [{"name": "intro", "bars": 8, "parts": ["funk-bass"]}]}'   # panels' riffs over sections
hands panel drop funk-bass                            # delete the track; renders stay
```

`make` adds a track called `panel NAME` at the end of the open set and renders the riff past the end of the
arrangement, at the spec's tempo. The clip, the render track, Live's take file, the tempo, the loop, the start marker,
the position, the selection and the arm states are put back, so it is safe beside a mix in progress; it refuses while
Live is playing. Parameter values are raw numbers, `"50%"` of the range, or the text Live shows (`"600 Hz"`,
`"-12 dB"`, `"Saw D"`); the knobs it prints carry Live's own readings (`display`). Renders and `NAME.panel.json` go to
`./renders` (`--out`). `hands/bin/hands` (in the repo) runs the CLI from any folder; link it into a folder on PATH.

## Scripts from real tracks

The batch scripts I wrote for particular pieces (HW002's probe packs, the industrial short, proptest, Marrow, the
Rummage, Juice Box, the checklist's sounds), and `hands plan` with its skills, are in a separate local repo,
zpkt-archive, since 24 November 2026; each needs the zpkt of git tag `pre-upgrade-2026-11-24` to run. What they still
had in common moved into the library: the menu export and Save As (`zpkt.live.export`) and the recipe steps
(`zpkt.live.ops`).

## Around zpkt.live

- Starting Live on a headless Mac: `lib/rig/start_headless.sh` (paths here are from the repo root).
- Skills for an agent that drives Live: `agent/`.
- `src/zpkt/live/remote_scripts/`: the Control Surface scripts (inside the package, so FakeLive finds them in an installed wheel) `install.sh` copies into Live's User Library.
  `AbletonLiveMCP` is the bridge (from opendining/ableton-mcp-server, MIT).
- `hands/macros/hammerspoon/`: my desk hotkeys (A/B against a reference, spectrum, backups) and the
  supervisor for `contrib/harness`. `config.lua` holds the paths.

## Tests

```bash
uv run --all-extras pytest -q -p no:cacheprovider tests/live     # from the repo root; `make test` runs both halves
```

Without `--all-extras` the Serum 2 tests are skipped, since their packages are optional. Types and style:

```bash
uv run --all-extras mypy        # config in the root pyproject.toml: strict for the Live library and the CLI modules
uvx ruff check . && uvx ruff format --check .   # the root ruff.toml
```

Everything runs offline: `zpkt.live.testing.FakeLive`, which runs the Remote Script's own code over a fake
Live set (`testing/README.md`), a fake Remote Script on a free port, fakes for osascript and the GUI, the
BSD fixture set in `tests/live/fixtures` with devices planted the way Live writes them, small synthetic
sets written by `tests/live/synth_set.py` for the library tests, and synthetic audio. Nothing in the
tests talks to Live or reads a real project.
