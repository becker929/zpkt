---
name: midi-parameter-mapping
description: Map any MIDI CC — from a software virtual port or a hardware controller (Arturia MiniLab, etc.) — to any Ableton Live 12 parameter, including track volume/pan/sends and configured VST/AU plugin parameters. Uses a config-driven control-surface script (AgentMap) that hot-reloads mappings at runtime with no GUI, plus a virtual MIDI port for agentic CC injection and an all-ports monitor to discover a controller's CC layout. Verify closed-loop by reading parameter values back over OSC. Use when asked to MIDI-map, assign or remap knobs/faders/pads to parameters, inject test CCs, or reverse-engineer a controller's CCs.
---

# MIDI -> parameter mapping in Ableton Live 12

Bind arbitrary MIDI CCs to arbitrary Live parameters, agentically and
verifiably. This complements the **ableton-live-control** skill (OSC/LOM access,
`scripts/live.py`), which you use here to read parameter values back and confirm
mappings fire. For keeping Live off the user's physical screen during the
one-time GUI step, use the **virtual-display** skill.

Read `reference/gotchas.md` before non-trivial work — it captures the Live
limitations (no LOM MIDI-map API, plugin params must be Configured, restart to
register new scripts, endless-encoder modes, sleeping controllers).

## How it works

`AgentMap` is a MIDI Remote Script (control surface). You assign its **Input**
to a MIDI port; it reads `config.json` (polled ~2x/sec) and, in `build_midi_map`,
binds each declared CC to a `DeviceParameter` via `Live.MidiMap.map_midi_cc`.
Editing `config.json` remaps at runtime with no GUI and no restart.

Two MIDI sources:
- **AgentVirtualMIDI** — a software virtual port (`midi_vport.py` daemon). Inject
  CCs with `send.sh`; fully agentic, no hardware needed.
- **A hardware controller** — assign AgentMap's Input to the controller's port.

## First-time setup (once per machine)

```sh
bash scripts/install.sh          # venv + python-rtmidi, install AgentMap script
```

Then (unavoidable one-time GUI, because Live only discovers new Remote Scripts
at launch):

1. **Restart Ableton Live.**
2. Settings -> **Tempo & MIDI** -> a free Control Surface row:
   - Control Surface = **AgentMap**
   - Input = your controller's port, or **AgentVirtualMIDI**
   - Leave row 1 (a factory controller script) alone; sharing a port usually
     works (see gotchas).
3. Start the virtual port daemon (if using it):
   ```sh
   bash scripts/vport.sh start
   ```

Driving the Settings dropdowns is custom-drawn UI: use `cliclick` at computed
points verified by screenshots (see `ableton-live-control`'s `snap.sh` and
`enable_osc.sh`, and the coordinate math in `reference/gotchas.md`).

## Standard workflow

Preflight with the companion skill's `doctor.sh` (Live up? OSC up?). Confirm
AgentMap is loaded:

```sh
uv run --project <zpkt>/hands hands live exec --json \
  "result = [cs.__class__.__name__ for cs in Live.Application.get_application().control_surfaces]"
```

1. **Pick the target parameter** and find its indices over OSC (ableton-live-control):
   ```sh
   python3 <alc>/scripts/live.py --json /live/track/get/devices/name <track>
   python3 <alc>/scripts/live.py --json /live/device/get/parameters/name <track> <device>
   ```
   For a **VST/AU** target, first Configure the param once in the plugin GUI (the
   hand icon + click the control) so it appears in `device.parameters`.

2. **Discover hardware CCs** (skip for virtual-port-only work):
   ```sh
   bash scripts/monitor.sh start     # clears log, opens ALL input ports
   # ask the user to move ONE control at a time; a sleeping controller sends
   # nothing until woken (wiggle/replug).
   bash scripts/monitor.sh summary   # shows port + CC/note counts
   ```

3. **Declare the mapping** (hot-reloads):
   ```sh
   python3 scripts/setmap.py add --cc 74 --target device_param \
     --track 5 --device 0 --parameter 8
   python3 scripts/setmap.py add --cc 82 --target track_volume --track 5
   python3 scripts/setmap.py list
   ```
   Or edit `~/Music/Ableton/User Library/Remote Scripts/AgentMap/config.json`
   directly (schema in the script docstring / `reference/gotchas.md`).

4. **Drive and verify (closed loop)**:
   ```sh
   bash scripts/send.sh CC 0 74 127                       # virtual port
   python3 <alc>/scripts/live.py --json /live/device/get/parameter/value 5 0 8
   ```
   For hardware, ask the user to move the control, then read the value back.
   Absolute CC value V maps linearly across the parameter range (V/127).

## Targets (config `target` field)

| target | resolves to |
|---|---|
| `device_param` | `tracks[track].devices[device].parameters[parameter]` (track may be `"master"`) |
| `track_volume` | `tracks[track].mixer_device.volume` |
| `track_pan` | `tracks[track].mixer_device.panning` |
| `send` | `tracks[track].mixer_device.sends[send]` |
| `master_volume` | `master_track.mixer_device.volume` |

Per-mapping options: `channel` (0-15, default 0), `mode` (any
`Live.MidiMap.MapMode` name, default `absolute`; use a relative mode for endless
encoders), `avoid_takeover` (default false = value sets param immediately).

## On-screen controller map (web bridge)

`webmap.py` mirrors the current mappings onto the interactive MiniLab 3 web
controller (`~/arturia-minilab3.html`), so **whenever you change a mapping it
shows up on the on-screen surface** — the matching knob/fader/pad is relabeled
with its Live target. It reads the same `config.json`, so `setmap.py` edits and
manual edits both propagate.

How the match works: each mapping is keyed by its raw MIDI CC. The bridge
translates that CC back to the physical control using the MiniLab 3 default CC
map (ARTURIA/User + DAW programs, which are disjoint), then writes a label for
the mapping's target onto that control. Unmapped controls show blank.

```sh
bash scripts/webmap.sh start            # serve http://localhost:8731/ (tmux daemon)
# open the page (any style): http://localhost:8731/?style=flat  (or ?style=hc)
python3 scripts/setmap.py add --cc 74 --target track_volume --track 5
# ...within ~1s the on-screen encoder 1 relabels to "Trk5 Vol"
bash scripts/webmap.sh status           # prints current labels.json
bash scripts/webmap.sh stop
```

Labels are structural by default (e.g. `T2 D0 P8`, `Trk5 Vol`). Add
`WEBMAP_RESOLVE=1` (or `--resolve-names`) to resolve **friendly Live names**
(actual parameter/track names) via AbletonOSC — requires the
**ableton-live-control** skill running. Inspect without a browser:
`python3 scripts/webmap.py --once`.

The page connects only when served over http (it polls `labels.json` each
second); opened as a plain `file://` it stays a standalone mock. The bridge
status pill in the page toolbar turns green when connected.

## Cleanup

```sh
bash scripts/vport.sh stop
bash scripts/monitor.sh stop
bash scripts/webmap.sh stop
python3 scripts/setmap.py clear         # drop all mappings
```
To fully remove: set AgentMap's Control Surface row to `None`, and delete
`~/Music/Ableton/User Library/Remote Scripts/AgentMap/`.

## Files

| Path | Purpose |
|---|---|
| `scripts/install.sh` | One-time: venv + python-rtmidi, install AgentMap into Live |
| `scripts/AgentMap/__init__.py` | The control-surface script (config-driven mapper) |
| `scripts/AgentMap/config.json` | Starter config (empty) |
| `scripts/midi_vport.py` | Virtual MIDI output port daemon (AgentVirtualMIDI) |
| `scripts/vport.sh` | start/stop/status the virtual port daemon (tmux) |
| `scripts/send.sh` | Inject a CC/NOTE/PB via the virtual port |
| `scripts/midi_monitor_all.py` | Log MIDI from all input ports (CC discovery) |
| `scripts/monitor.sh` | start/dump/summary/stop the monitor (tmux) |
| `scripts/setmap.py` | Edit AgentMap's config.json (add/remove/list/clear) |
| `scripts/webmap.py` | Bridge config.json -> MiniLab 3 web controller (serves page + live labels.json) |
| `scripts/webmap.sh` | start/stop/status/url the web-controller bridge (tmux) |
| `reference/gotchas.md` | Live limitations and hard-won facts — read this |
