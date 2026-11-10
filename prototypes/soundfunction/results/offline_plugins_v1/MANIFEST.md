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

---

## Addendum, same day: step 4 done under DawDreamer

pedalboard could not run the LFO. DawDreamer can. `lab/dd_sweep.py`:

- Loads the **VST2** build, `/Library/Audio/Plug-Ins/VST/LFOTool.vst`, the
  same binary Live hosts. 70 parameters.
- Sets BPM 160 and renders with the transport playing.
- Applies Anthony's state **by name from the pedalboard dump**, then reads
  every value back. 69 of 70 match; the one pedalboard calls `warp_10` the
  VST2 side names `Warp 0:`, a labelling quirk with no bearing on depth.
  DawDreamer's own `load_state` did not accept the raw `.als` buffer.
- One caveat worth knowing: a fresh VST2 instance already came up carrying
  Anthony's settings before any load, so the plugin remembers its last state
  on this machine. Do not take "fresh instance" to mean "default".

Thirteen depths on the trimmed, un-ducked rumble, each divided against that
same input. Because both sides of the division are one deterministic render
there is no two-take alignment noise, and the measure now returns depths,
not floors. See `dd_sweep/depth_table.json` and `dd_sweep/known_answer.md`.

| depth | sub dip dB | low dip dB | sub minus low |
|---:|---:|---:|---:|
| 0.250 | 1.41 | 1.64 | -0.23 |
| 0.500 | 3.12 | 3.62 | -0.51 |
| 0.750 | 5.27 | 6.04 | -0.76 |
| 1.000 | 8.10 | 9.35 | -1.25 |

At full depth, Anthony's setting, the measured dip is 8.1 dB in the sub and
9.4 dB in the low band, against the 8.9 dB the curve floor predicts. The
split reads within about 1 dB of zero at every depth, the tool's own stated
tolerance. **One curve, both bands, about 9 dB.** That is the calibration at
known depths the spec asked for, and it agrees with the device's own state.

Also in this pack's commit: `lab/runner.py`'s new name-first pair selector
used `\b`, which never matches after an underscore, so `02__kick.wav` fell
through to physics and HW002 was paired backwards even after the fix. Now
`(?<![a-z])`. The refreshed bench pairs kick into rumble; its 70 dB headline
is still the saturating estimator and should still not be read as a depth.

---

## Addendum 2: the fixed bypass tool (093df1c) on both pairs

Same 13 DawDreamer renders, re-measured; plus the real aligned two-take pair
from `live_rumble_bypass_v1`. Files under `fixedtool/`.

**Deterministic pair (one render, on divided by off).** `gain_dip_db` now
tracks the curve floor: at depth 1.0 it reads 8.21 dB sub and 8.73 dB low
against a predicted 8.92; at 0.5 it reads 3.25 and 3.34 against 3.36. Both
bands agree within 0.5 dB at every depth. The split climbs slowly with depth
to 1.46 dB at full, from the onset gains. This is the calibration the spec
asked for, and it says one curve, both bands, about 9 dB.

**But `gain_at_beat_start_db` does not read the floor on that same pair.**
At depth 1.0 it gives -2.34 sub and -0.89 low. The dip is real and correct;
the value the tool samples at "beat start" is not the dip. The reference
kick's onset and LFOTool's cycle start are not the same instant, so the
onset sample lands part-way up the ramp.

**Real two-take pair.** Same tool: sub onset -7.12 dB, low onset -0.02 dB,
split +7.10, alignment lag -1 sample. Dip values are still floors (35 to 58
dB). The sub number is close to the device; the low number is zero, which
the deterministic pair says is wrong. With alignment at one sample this is
not a lag problem. Two real-time takes differ in the low band at onsets in a
way one render divided by itself cannot, and I cannot tell from here whether
that is the recorder, the kick group's compressor upstream of nothing (it is
not in this path), or the tool. Reported as-is for the tool's author.

**Reading.** Trust the deterministic-pair `gain_dip_db` column. Do not read
the onset column as a depth on either pair until its anchor is checked
against LFOTool's cycle start rather than the kick onset.
