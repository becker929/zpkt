# Decisions

The choices that shape the work, and why. Reverse any of them knowingly, not
by accident.

**Audio is never redistributed.** The corpus is mostly CC BY-NC-ND, which
forbids derivatives; a separated stem is a derivative. Anthony's own material
is his. So stems, bounces and downloads stay local and only numbers are
published. This ruled out serving corpus stems as listening-test stimuli, and
it is why the research repository's history was squashed before pushing: the
old history contained 2,660 stem files.

**The listening test uses real, redistributable one-shots.** The synthetic
stimuli failed 40% of feature checks against real sounds of the same job.
The replacement takes a real CC BY / CC0 / public-domain one-shot and changes
one thing. Credit lines travel in `pairs.json` and render on the page. Answer
sets are labelled (`v1-synth`, `v2-real`) so old answers are never pooled
with new.

**Measurements run where the audio is.** Audio is large and his. The Mac
runs the lab; the web session (now retired from the loop) received JSON.
Clips, if ever needed, are capped at 30 s and 20 MB.

**Calibrate before claiming.** Three instruments in a row were bent this
week. The rule is now explicit: no published number without a control that
returns a known answer. Where a measure saturates, the number is reported as
a floor.

**Plain language, enforced.** Research pages pass `tools/plainlint.py`.
Notes are looser but were rewritten when Anthony found them "too Claudish".
Dates are calibrated against the commit record.

**Notes carry a byline.** "Written by <model>, addressed to Anthony", at his
request. Notes 1 to 10 say Claude Fable 5.1. No model names anywhere else.

**One agent holds the mandate.** As of 12 Sep the Mac agent does. The
mailbox PR stays as a log and a place to ask the web session for review; it
is not a wake channel any more. Reason: the two-machine design cost a poll
that never fired, permission refusals, and every result relaying through
Anthony.

**Plugins are swept offline; native Live devices on the rig.** pedalboard
exposes every plugin parameter and renders faster than real time; the Live
API hid LFOTool's parameters entirely. Native devices (Drum Rack, EQ Eight,
Roar, Compressor, Simpler) still need Live.

**The knob map prefers monotonic, spectrally orthogonal knobs.** The
StandardCLIP threshold inverts cleanly into a target crest; Decapitator Drive
does not. When the assistant proposes a move it should reach for the former.

**Three ntfy levels, and nothing else to Anthony.** `fyi` silent, `ask`
normal, `act` high and mirrored into Apple Reminders by a Mac-side
subscriber. Gmail, Calendar and Messages were considered and not used.

**Sweep the whole range at a deliberate step.** Endpoints alone hid the
Decapitator hump; 0.1 steps co-located two extrema that 0.025 steps separate.
Pick ranges that cross the band edge being measured, or a share saturates
flat and reads as "no effect".

**Tap pre-group for any A/B.** The rumble sits inside a kick group with
nonlinear devices; soloing the master would push both takes through
processing that reacts differently to different inputs.
