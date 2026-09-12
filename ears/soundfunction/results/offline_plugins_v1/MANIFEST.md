# offline_plugins_v1 — plugin sweeps off the DAW, steps 0 to 4

Job: mailbox comment 5644358857. Move plugin sweeps to pedalboard. Steps 0 to
4 attempted; step 5 not started, see the end.

## The two results that matter

**1. Anthony's actual LFOTool setting is now known.** Step 3 worked end to
end: the rumble track's `PluginDevice` `Buffer` was pulled out of the clone's
`.als`, decoded, loaded into the LFOTool Audio Unit through pedalboard, and
dumped. All 70 parameters are in `lfotool_state/rumble_state_dump.json`; the
ones that decide the question are in `lfotool_setting.md`. In short: synced,
one cycle per beat, full depth, **volume only**. Filter off, crossover off,
cutoff and resonance modulation at zero. The drawn curve starts each beat at
0.358 of full gain, about **9 dB down**, and returns to unity by the end of
the beat.

That corrects the earlier `live_rumble_bypass_v1` MANIFEST. Its "ducks to
near silence" was the two-take division bottoming out on noise, not the
device. The broadband conclusion stands and is now read off the device.

**2. LFOTool cannot be swept in pedalboard.** Step 4 rendered 13 depth steps
at 985 times real time and every one measured 0.00 dB of duck, full depth
included. The render at depth 1.0 differs from its input by 1e-4 peak. The
LFO does not advance without a host transport, and pedalboard 0.9.25 exposes
none: no tempo, no play state, no playhead. Switching the plugin to Free
mode makes no difference, and its `rate` stays a list of note divisions in
either mode. This is the case the plan reserved for DawDreamer, which does
drive a transport. The sweep outputs are kept under `depth_sweep/` as the
evidence, not as data.

## Step by step

- **0. `autodaw` check.** Nothing there mentions pedalboard or DawDreamer.
  Built fresh.
- **1. Install.** `pedalboard 0.9.25` into the lab venv from
  `requirements.txt`.
- **2. Parameter lists.** Under `plugin_lists/`. LFOTool 70 parameters,
  Dist COLDFIRE about 270, StandardCLIP 6. **Decapitator: zero.** Its Audio
  Unit loads, names itself, and exposes no parameters and zero bytes of
  state. It cannot be swept or preset-driven from here as things stand.
- **3. State round trip, read direction.** Worked, see above. Two facts the
  spec had wrong: the `Buffer` is hex text, not base64; and Live hosts every
  one of these plugins as legacy VST2 (`VstPluginInfo`), while pedalboard
  loads the Audio Unit. The VST2 chunk loaded into the AU cleanly, so for
  LFOTool the two formats share a state layout. Not guaranteed for others.
- **4. Depth sweep.** Rendered, measured, flat. See above.

## What fought us

- **Audio Units do not load inside tmux.** Every plugin call under tmux
  failed with "unsupported plugin format or scan failure"; the same command
  from a foreground shell works. The tmux server sits outside the GUI
  bootstrap namespace the AudioComponent registry needs. Run plugin work in
  the foreground, or from a launchd agent in the `gui` domain.
- **Decapitator, as above.** Likely wants its own authorisation or GUI
  pass before it publishes parameters. Untested beyond a second load.
- **The rate parameter is an enum.** No Hz value can be set, so a
  free-running sweep at a chosen frequency is not possible even if the LFO
  ran.

## Step 5

Not started. Its premise was a swept state to round-trip; there is no valid
swept state. Round-tripping Anthony's own state back into Live would only
prove Live can load what Live saved. Both `.vstpreset` routes are also moot
for a VST2 instance; the `.adv` or `.als` route is the one that applies.

## Suggested next

DawDreamer for LFOTool, with BPM 160 and the transport playing. Same state
file, same input, same 13 depths, then `duck_calibration.py bypass` on each.
That yields the calibration at known depths the spec was after.

No audio in this pack. No audio left the machine.
