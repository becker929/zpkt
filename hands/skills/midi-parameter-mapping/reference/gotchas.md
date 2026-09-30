# MIDI parameter mapping: gotchas and hard-won facts

Verified against Ableton Live 12.4.5 Suite on macOS (Apple Silicon), with an
Arturia MiniLab 3.

## Why a control-surface script (and not OSC/Cmd+M)

- The Live Object Model exposes **no API for the Cmd+M user MIDI map**. You
  cannot read or create those mappings over OSC or the MCP LOM path.
- The only programmatic route is a **control surface** that calls
  `Live.MidiMap.map_midi_cc(handle, parameter, channel, cc, mode, avoid_takeover)`
  inside its `build_midi_map(handle)` callback. `AgentMap` is exactly that.
- `map_midi_cc` accepts any `DeviceParameter` object, so it maps stock device
  params, mixer params (volume/pan/sends), and configured plugin params alike.

## New Remote Scripts need a Live restart

- Live scans `Remote Scripts/` **only at launch**. After `install.sh` copies
  AgentMap in, you must restart Live before it appears in the Control Surface
  dropdown. Release Live has no "reload scripts" menu (that is beta-only).
- Selecting AgentMap on a row + its Input port **persists** in Preferences, so
  this GUI step is one-time.

## Editing AgentMap's own code vs its config

- Changing `config.json` hot-reloads (~2x/sec) via a scheduled tick; no restart.
- Changing `__init__.py` (the script code) requires a Live restart to take
  effect (re-import happens at launch).

## Plugin (VST/AU) parameters must be Configured once

- For a freshly loaded plugin, `device.parameters` contains only **"Device On"**.
  `device.get_parameter_names()` may list thousands of names, but only exposed
  ones become mappable `DeviceParameter` objects.
- To expose one: in Live's device view click the plugin's **Configure** button
  (the hand icon in the device title bar), then click the control in the plugin
  editor window. It then appears in `device.parameters` and maps like any param.
- There is no headless API for this Configure step; it is a one-time GUI action
  per parameter.

## Hardware controllers

- **Endless encoders** often send absolute values that pin at 0/127, or relative
  values, depending on the controller's mode. Check with the monitor. For a
  relative encoder set the mapping `"mode"` to a relative MapMode, e.g.
  `relative_two_compliment` (values ~1 up / ~127 down) or
  `relative_signed_bit`.
- An **idle/asleep controller sends nothing** until woken. If the monitor
  captures zero messages (not even a keyboard note), have the user wiggle a
  control or replug; Arturia devices emit an Identity Reply SysEx on wake.
- Controllers expose **multiple ports** (e.g. `Minilab3 MIDI`, `Minilab3 MCU`).
  In DAW mode the interesting controls may be on the main MIDI port; monitor all
  ports (`midi_monitor_all.py`) and read the port tag on each line.
- CoreMIDI **multicasts** a source to all clients, so the monitor can read a
  controller at the same time Live's own script does.

## Sharing a port with a factory control surface

- You can point AgentMap's Input at the same physical port that the controller's
  factory script (e.g. `MiniLab_3` on row 1) uses. In testing, AgentMap's
  `map_midi_cc` bindings worked without disabling the factory script, as long as
  the CC you map is not already consumed for the same target by that script.
- If a mapping seems ignored, set the factory script's row to `None` (or change
  its Input) to give AgentMap sole ownership of the port, then retest.

## avoid_takeover / map mode

- `avoid_takeover=False` (default here) makes the incoming CC value set the
  parameter immediately — best for scripted verification.
- `avoid_takeover=True` is soft/pickup takeover: the parameter will not move
  until the incoming value crosses the current value. Handy live, annoying when
  testing.

## The one-time Settings GUI (selecting AgentMap + Input port)

- Live's Control Surface table is custom-drawn; the accessibility API reports
  the **same position for every row** and does not expose the dropdown values.
  Drive it with `cliclick` at computed screen points, verified by screenshots.
- Page navigation in Settings: pressing the sidebar page-chooser via AXPress can
  be flaky; clicking the page by computed coordinate is reliable. In 12.4 the
  MIDI/Control-Surface table is under the **"Tempo & MIDI"** page (separate from
  "Link").
- On a Retina virtual display, `screencapture -R X,Y,W,H` uses **logical
  points** for the region but writes a **2x pixel** image. Map an image pixel to
  a logical click point as: `logical = region_origin + raw_pixel/2` (and
  `raw_pixel = downscaled_pixel * raw_width/downscaled_width`).
- See the sibling `ableton-live-control` skill for `snap.sh`, and for keeping
  Live off the user's physical screen use the `virtual-display` skill.
