# live_rumble_bypass_v1 — LFOTool's own gain curve, measured

Job: section 3 of `research/next.md`. Bounce HW002_14 track 3 (`rumble`)
twice from one copy-on-write clone, once as it is and once with only LFOTool
bypassed, then divide the two to recover the device's gain curve per band.

Complete. Both bounces ran, the measurement ran, and the headline is below.
Two real errors were made and corrected on the way; both are written up in
"What fought us", because both change how the numbers should be read.

## The answer

**LFOTool applies one broadband duck, not a split. And it ducks to silence.**

Two things establish this.

**Timing.** The sub band bottoms out 344 ms into the beat, the low band 16 ms
into it. The beat is 375 ms at 160 BPM, so those are 31 ms apart, not 328.
Both bands are pulled down at the same instant by one curve.

**Depth.** The reported depths are 37 dB in the sub and 56 dB in the low.
Neither is a measurement. `duck_calibrate.json`, re-run on this machine,
shows the measure saturates above about 12 dB: a true 24 dB duck reads 11.8,
a true 40 dB reads 13.4. Anything past ~13 dB is the estimator hitting a
floor. A 37 and a 56 are two different noise floors, one per band, not two
different duck depths.

| window | sub dip dB | at ms | low dip dB | at ms | sub minus low |
|---|---:|---:|---:|---:|---:|
| 30 s at 35% | 37.62 | 344 | 56.16 | 20 | -18.54 |
| 30 s at 50% | 36.51 | 336 | 55.43 | 8 | -18.92 |
| 30 s at 65% | 38.02 | 340 | 56.51 | 16 | -18.49 |
| 30 s at 80% | 38.10 | 340 | 56.58 | 16 | -18.48 |

So `sub_minus_low_db` of about -18.5 must NOT be read as "the low band is
ducked 18 dB deeper". It is the gap between two noise floors. An independent
beat-synchronous fold, run as a cross-check outside the tool, makes this
plain: it returns -46 dB in the sub, -55 dB in the low and **-120 dB in the
mid 150-400 Hz band**. A shaper cannot attenuate by 120 dB. That band simply
has almost no signal left to measure, and neither do the other two.

This settles the open question from `multitrack-first-results.md`. That page
said the sidecar recorded device names but not values, so it could not tell
whether LFOTool shapes volume or a filter. It shapes volume, broadband, to
near silence between kicks. The split duck is not merely declined on taste
here; it is not what this device is doing.

## What ran, and on what

Machine: Anthony's MacBook Air, macOS 26.3, arm64. Python 3.12.8 venv.
Live 12 Suite, Path B (`AbletonLiveMCP`, TCP 16619) throughout. Six feature
tests passed before any of this.

All three audio files were recorded in one sitting, from one clone, by the
tap-and-record mechanism `bounce_multitrack.py` proved: the source track's
own output is routed into a capture audio track and the arrangement is
recorded in real time.

- `03__rumble.wav` — LFOTool on, verified `parameters[0].value == 1.0`.
- `03__rumble__lfotool-off.wav` — LFOTool off, verified `== 0.0` in a call
  separate from the write, per the Path-B crash rules.
- `02__kick.wav` — re-bounced in this same session.

Tapping the track's own output matters and was a deliberate choice. `rumble`
sits inside `kick group`, which carries a Compressor, Roar and Dist COLDFIRE.
Soloing and rendering Main would have pushed both takes through nonlinear
processing that reacts differently to a ducked and an un-ducked input, which
would have contaminated the division. The per-track tap is pre-group.

LFOTool was restored to on and the capture track disarmed at the end. The
clone was never saved. The original `.als` was never opened.

## What fought us

**1. The first pass recorded six minutes of silence.** The rig sized each
pass from `song.last_event_time`, which is the last event anywhere in the
set: 1630 beats, or 616 s. The rumble track's own content ends at beat 704,
or 264 s. So 57% of the first bounce was silence. Anthony caught this on the
second pass and stopped the transport. The fix is to size a bounce from the
source track's own `arrangement_clips`, not from the set. Worth noting for
the register: **the stems in `live_multitrack_bounce_v1` have the same
defect.** `02__kick.wav` and `03__rumble.wav` there are 614 s of which about
264 s is music. Any measure run on them was reading majority silence, which
is a plausible contributor to the 40 dB and 70 dB nonsense that page reports.

**2. The two takes were not aligned, and the first measurement was garbage.**
Two separate real-time recordings do not start on the same sample. The
offset here was 251 samples, 5.7 ms. Run unaligned, the tool returned
`sub_minus_low_db` of -24 with depths wandering between windows. A naive
cross-correlation made it worse by locking onto a lag of 374 ms, which is
one beat at 160 BPM, an artifact of the material's own periodicity.
Constraining the search to well inside one beat found the true 251 samples.
After alignment the four windows agree to within 0.5 dB. The aligned files
carry the `aligned__` prefix. **Any future two-take comparison on this rig
must align first, and must constrain the lag search to less than one beat.**

**3. LFOTool's parameter values cannot be read at all.** The spec asked for
them in the sidecar. They are not available by any route tried. Over the
Live Object Model the device exposes exactly one parameter, its on/off.
In the project XML the plugin state is a single opaque `Buffer` inside
`VstPluginInfo`, with no `PluginFloatParameter` or `ParameterName` entries.
Both sidecars record this explicitly rather than leaving the field blank.
The bypass measurement answers the underlying question without them.

**4. The kick's alignment is unverified.** Aligning the kick to the rumble by
correlation returned a peak of 58, against 6945 for rumble against bypass.
Two different instruments do not correlate usefully. The kick is only used to
locate beats, so this affects where the dip is reported, not how deep it is,
and the four windows agreeing suggests it is not distorting the result. It is
still an assumption rather than a check.

**5. The fast export path was unreachable.** Live's native Export dialog
renders faster than real time and can isolate one track, and the skill has a
verified driver for it. It needs `osascript` assistive access, which this
session does not have: every System Events call returns error -1728. Screen
control of Live was granted, but the Rendered Track chooser is a pop-up menu
that background control cannot open, and the full-screen approval went
unanswered. So the job fell back to real-time capture. Three passes at 4.5
minutes each instead of three at about one.

**6. The Reminders mirror is still not installed.** Posting to ntfy works and
was used throughout. The launchd install was refused by this session's
permission layer, so high-priority messages create no Reminder.
`MAILBOX_PR` has been set to 25 in `ops/local.env` now that the mailbox
pull request exists.

## Files

- `duck_bypass.json` — the answer. Read the depths as floors, not depths.
- `duck_calibrate.json` — the saturation control, from the same real kick.
  This is what licenses the reading above.
- `03__rumble.params.json`, `03__rumble__lfotool-off.params.json` — one per
  take. Full device chain with every exposed parameter, plus an explicit note
  on why LFOTool's own values are absent.

No wav files are in this pack. No audio left the machine.
