# Ableton readout checklist

Go through every region below, in every frame where it changes, before writing the recipe. Crop each region
at 2–5× with `crop.py` (lanczos, PNG). Tag what you record: **seen** if it was read on screen, **inferred**
if it was measured or reasoned. DAW text is often truncated, and "?" is the honest answer.

## Regions

| Region | Where | Record | Trust |
|---|---|---|---|
| Control bar | top left | tempo, time signature, metronome, quantization menu | high (large text) |
| Loop and punch | top centre to right | loop on, loop start, loop length (bar.beat.sixteenth) | high |
| Grid indicator | bottom right of the arrangement (e.g. "1/8") | fixed or adaptive grid, and its value. The value shown may not be the one the edits used: check placements against it | medium |
| Status bar | bottom edge, the richest source | the selected clip's name, start, end, length and file path; the insert mark; a time selection's length **with its duration in seconds** (tempo cross-check: 2.0.0 = 3.902 s at 123 BPM) | high when legible; crop it at 3–4× |
| Mixer section | right of the tracks | volume (dB), pan, sends, solo, mute, arm, track numbers | high for numbers; small type needs a 3× crop |
| Track headers | left of the lanes | names, colours, collapsed or expanded, groups, track type (audio, MIDI or return: an arm button, the clip style) | names high; type is often inferred |
| Clip headers | top strip of each clip | name (often truncated), start and length against the ruler (`pixels.py rowscan`), deactivated (grey), selected (grey header: missed by rowscan, so check by eye) | positions high once calibrated on two ruler ticks |
| Waveforms | clip bodies | transient columns and relative heights (`pixels.py colprofile`); empty clips | timing good, loudness rough |
| Ruler | above the lanes | two ticks far apart, for the pixel-to-beat scale | high |
| Device view | bottom, when open | device names, the chain order, each visible parameter with its unit, the macro names and values, the on/off state | high when shown; often never shown |
| Clip view | bottom, when open | warp on/off and mode, gain, transpose, detune, start/end, loop, signature, launch settings | high when shown |
| Piano roll / MIDI editor | clip view | note pitches (read the keyboard labels; Live names C3 = 60), starts, lengths, velocities (the velocity lane), fold, scale | high |
| Automation lanes | under the tracks | the chooser's current value, breakpoints and their values. Flat and dashed means no automation | medium |
| Browser | left, when open | pack and sample names, the search terms used | names high, full paths rare |
| Session view | when shown | slots, scenes, follow actions, the clip colours | high |

## Rules

- **A pointer over a control is not a click.** Trace the control's state (lit or not, value) across frames
  at 5–10 fps before you claim an action. In run 1 a solo button was lit from the first frame; the pointer
  only rested on it.
- **The starting state often already holds the result.** Claim only the actions you saw happen.
- **Decide the medium early:** audio clips or MIDI, devices shown or not. With audio clips, pitch and
  velocity have to be measured from the audio.
- **Read the version.**
  - A Live 10 or 11 UI differs from Live 12: the master track became Main, and some menus moved.
  - Name devices as Live 12 Suite has them.
  - Check every device and parameter named in the recipe exists under that name.
- **Record two zoom levels when you can.** The run 1 positions agreed within 0.02 beat across two zooms.
- **Confirm positions in the audio.** Positions read from pixels are confirmed by audio onsets after
  `anchor.py`. They agreed within 0.03 beat in run 1.
- **Read numbers only from crops.** Never read a number off a contact sheet.
