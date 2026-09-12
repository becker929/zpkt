# Plugins outside the DAW: pedalboard and DawDreamer

Written 12 September 2026, after LFOTool turned out to expose only its on/off
to the Live API and to store its settings as an opaque blob.

## What this changes

Most of what the knob map needs to touch is a plugin: Decapitator, LFOTool,
Dist COLDFIRE, StandardCLIP. Driving them through Live means real time, a
person awake at a Mac, and, for LFOTool, no parameter access at all.

pedalboard (Spotify) hosts the same VST3 or AU binaries from Python. It
exposes every parameter with its name, range and display text, renders
faster than real time, and reads and writes the plugin's raw state. Measured
here on a built-in effect the sweep harness renders at over a thousand times
real time. DawDreamer does the same and can also host a whole graph of
plugins and instruments with a timeline, closer to a full offline DAW.

So the map splits in two:

| device kind | where it is swept | why |
|---|---|---|
| Plugin (VST3 or AU) | offline, `lab/plugin_sweep.py` | every parameter visible, fast, deterministic, no Live session needed |
| Native Live device (Drum Rack, EQ Eight, Roar, Compressor, Simpler) | Live, the existing rig | not loadable outside Live |

The rig is still needed for the native devices and for bouncing the input
stems the offline sweeps run on. Everything else moves off the rig.

## The preset round trip

The point of reading and writing state is that a setting found offline has to
be loadable in Live, or it is only a number.

Three routes, in order of preference:

1. **`.vstpreset`.** The VST3 standard preset file. pedalboard's
   `load_preset` reads them; most VST3 plugins save and load them from their
   own preset menu inside Live. pedalboard's `raw_state` is the same state
   stream a `.vstpreset` wraps, so writing one from a swept setting is a
   header plus the bytes. This needs a one-time check per plugin that Live's
   instance accepts it.
2. **The `.adv` device preset.** Live's own preset format for a device on a
   track: gzipped XML in which a `PluginDevice` holds the plugin state as a
   `Buffer` element. Writing swept state into that buffer produces a preset
   Live loads by drag. Same bytes as route 1, different wrapper.
3. **The `.als` itself.** The clone's project file holds the same `Buffer`.
   Editing it and reopening the clone sets the plugin without touching the
   Live API at all. Slowest, and it needs a reopen, but it is how a sweep
   could be driven through Live for a device the API hides.

The reverse direction matters just as much: pull the `Buffer` out of the
`.als` for the rumble's LFOTool, load it into the offline instance, and read
the settings Anthony actually uses. That is the answer to "what is LFOTool
set to", which the Live API could not give.

## First job on the Mac

Check before building. The `autodaw` project on the laptop may already carry
a working demonstration of some of this; if it does, use it and say so.

1. `pip install pedalboard` in the lab venv (it is in `requirements.txt`).
2. `python3 lab/plugin_sweep.py list --plugin <path>` for LFOTool, Decapitator,
   Dist COLDFIRE and StandardCLIP. Paste the parameter lists back. That alone
   tells us which knobs exist and what their ranges are.
3. Extract the LFOTool `Buffer` from the HW002 clone's `.als` (gunzip, find
   the rumble track's `PluginDevice`, base64-decode the buffer), load it with
   `plugin_sweep.py state --plugin <LFOTool> --load-state <file> --dump`, and
   paste the dump. That is Anthony's actual LFOTool setting.
4. Sweep LFOTool's depth (whatever it is called in the list) on the trimmed,
   bypassed rumble render, 13 steps over the whole range, and run
   `duck_calibration.py bypass` on each output against the bypassed input.
   This produces the first offline row of the knob map and calibrates the
   duck measure at known depths on real material.
5. Round trip: save one swept state, wrap it as a `.vstpreset`, load it in
   the clone's LFOTool from the plugin's own preset menu, and confirm by ear or
   by a short bounce that Live took it. If the menu route fails, try the
   `.adv` route. Report which worked.

Return numbers, parameter dumps and the MANIFEST. No audio.

## What this does not replace

The bench sheet, the corpus and the listening test are unchanged. This is a
faster, more complete way to build the knob map for plugin devices, and the
only way to read settings the Live API hides. Native devices still go
through the rig.
