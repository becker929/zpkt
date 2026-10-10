---
name: render-plan
description: Render plans (a probe kit plus knob values for one section) in Ableton Live, several in one load and one export, and keep every render in the cache. Use in a studio voice session when Anthony asks to hear a change ("kick drive up", "brighter chord") and the section has a probe kit; also to list a kit's tempo and a knob's value and range before choosing values.
---

# render-plan

A **plan** is a small JSON document: which knobs of a probe kit take which values, for one section.

```json
{"kit": "c8x4", "knobs": {"rumble|plugin:Decapitator|Drive": 0.5}, "label": "rumble drive 50%"}
```

- `kit`: a probe kit (`hands/scripts/probe_pack/probe_kit.py`): a copy of the set trimmed to a lead-in plus one
  section repeated P times. Kits are built once, in the GUI; their metadata is in `~/_agent_scratch/probepack/kits/`.
- knob ids are `<track>|<device>|<parameter>`: device `Mixer` (`Volume`, `Pan`), `plugin:<name>` (parameter = the
  plugin's display name, value 0-1), or `<DeviceTag>:<index>` for Live devices (`Eq8:0`, parameter = XML path such
  as `Bands.1/ParameterA/Gain`, value in the device's units). Knobs a plan leaves out keep the kit's value.
- `label` is what Anthony hears it called. Say values the way he would ("drive 50 percent").

## Commands (run from `hands/`, `uv run --extra plans hands plan ...`)

```bash
hands plan kit c8x4                                   # version, tempo, bar length, P
hands plan knob c8x4 'rumble|plugin:Decapitator|Drive'   # its value and range in the kit
hands plan render PLAN [PLAN ...]                     # renders what is not cached, P plans per Live pass
```

A PLAN argument is inline JSON or a file. Every command prints JSON; `render` gives each plan's `audio` (a WAV of
the whole pattern, first bar = the previous pattern's tail) and whether it was cached.

## Rules

- A render loads the kit's batch set in Live and exports it (about 7 s + 13 s + a tenth of the audio). It goes
  through probe_kit's guards: no dialog open, one of our `HW002_121_pp*` sets in front, Live answering. If a guard
  stops it, stop and tell Anthony what it said; never retry blindly or switch his set.
- Pack: if you will want several versions, give them to one `render` (or use `ab`, skill ab-1bar), not one by one.
- To let him hear a render, use `ab` (ab-1bar) against the current version, or `mcp__studio__present_music` with the
  WAV. Never offline DSP to change the sound: changes are knob values rendered in Live.
