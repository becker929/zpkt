# 10 — Collage

## What the material actually is

HW011 is the first real project and it settles what this view is for. Fifteen
sounds, 36.2 minutes of wall time, 24.8 minutes of sound. One file is 293
seconds long and holds 20 seconds of audio. Another is nearly 15 minutes and is
entirely speech. The shortest is 6.4 seconds.

These are not clips waiting to be arranged. They are **sources**, mostly sparse,
and the first job is getting material out of them. Collage is a region extractor
before it is an arranger. Cut is what makes move and balance possible.

## No seconds, no grid

The interface never shows a time ruler, a bar line, a grid, or a number of
seconds. Not as a default to be turned off — it is not built.

This material is non-metric on purpose: no instruments, no drums, no tempo. A
grid would impose a pulse the sound does not have, and a numeric position
invites arithmetic instead of listening. Both would quietly turn this into the
general-purpose tool it is explicitly not.

What replaces them: width means duration, overlap means simultaneity, and
position is set by dragging until it sounds right. The model stores seconds
because rendering needs them. The interface never says one.

The same rule applies to balance. Loudness is set by ear against the other
regions, and no decibel figure appears.

## The surface

Mobile first, and chunky. Time runs **down** the screen; tracks run **across**
it. Scrolling through time is the gesture a thumb already knows on a phone held
upright, and moving between tracks is a sideways swipe. A horizontal timeline is
an artefact of landscape monitors and is not built.

**It starts with nothing.** No time, no tracks, no empty lanes. Time exists
because a sound was stamped into it, and a track exists because something was
stamped there. Nothing on screen invites filling.

## The gestures, in the order they are built

Each is a tracer bullet: the thinnest slice that works end to end — interface,
model, file on disk, and audible playback — followed by an adversarial usability
review on a phone before the next one starts.

1. **Choose the first sound, then stamp it.** Pick from the project's frozen
   set. Tap the canvas to stamp the sound there: a region appears, the first
   track comes into being, time now extends as far as that region does. Stamp
   again for another region; stamp beside it for another track.
2. **Trim.** Tap a region's end to select its handle, then drag it.
3. **Snip.** A mode, entered by a button. Drag across a region to remove that
   part of it, leaving two regions.
4. **Stretch.** Tap a handle to select it, then enter stretch mode by button
   and drag. The region's playback rate follows.
5. **The rest of the sounds, and hearing them together.** Adding the other
   fourteen is the same gestures again. What is new is playing the collage:
   every region on every track scheduled at its `at_s`, at its `rate`, mixed.
   Until this bullet the view has only ever played one region alone. This is
   the first time the user hears the piece rather than a piece of it.

## The second set of gestures

Asked for on 2026-09-20, once the first five were in use. Built the same way:
one tracer bullet at a time, each adversarially reviewed before the next starts.

6. **Balance.** Take a region up, enter balance by button, drag across its box.
   The region's fill lightens or darkens, so loudness is weight you see rather
   than a figure you read. `gain` is already in the model and already applied
   per voice. Range 0 to 2.
7. **Move, copy, and removing a track.** Drag a region's *body* to translate it
   in time and across tracks. Copy a region and paste it by stamping. Remove a
   whole track and let the ones beyond it close up.
8. **Loop.** A region can repeat. The transport can loop the piece.
9. **Pitch.** Shift a region's pitch without changing how long it lasts.

### Balance, and why the master saturates

Fifteen voices at unity gain summed plainly will clip, and there is no master
fader because there is no number anywhere on this surface.

So the mix bus **soft-clips** rather than tearing: a gentle waveshaper, so
overload arrives as drive instead of as digital splintering. For this music that
is not a compromise, it is the sound. There is nothing to configure and nothing
to read; push more in and it gets harder.

Gain runs 0 to 2, so a quiet field recording can be brought up and a loud one
pushed past the others. No decibels, no fader, no number.

### Move is the body, trim is the handles

Dragging a region's **body** moves it: down or up to change `at_s`, sideways to
change `track`. No mode, because none is needed — the handles already mean trim
and the body is free. A tap on the body still plays and takes up; a drag moves.

A track holds regions that do not overlap, which stamp already maintains. A
move that would land on top of a neighbour settles after it, exactly as a stamp
does.

### Copy is a stamp

Take a region up, tap copy, then tap the blank where it should go. That is the
stamp gesture unchanged, with a region on the clipboard instead of a sound from
the picker, so there is nothing new to learn. A pasted region is a new `id`
with the same `hash`, cut, rate, gain, pitch and loops.

### Removing a track destroys its regions

So it is armed the way a whole-region snip is: **hold it for 600 ms**, with the
track and everything on it drawn in amber over the hold. A lift before then does
nothing. Tracks beyond the removed one close up, their `track` shifted down by
one. This is the second destructive gesture on the surface and it uses the same
language as the first.

### Loops

`loops` is a whole number, 1 by default: how many times the region's material
repeats, back to back. Its footprint becomes `(end_s − start_s) / rate × loops`
and its box grows to match, drawn with a divider where each repeat begins so the
eye can count them without a number.

Looping the **transport** is different in kind: it is how you listen, not part
of the piece, so it is not in the model and not in the digest. A toggle by the
transport; when the piece reaches its end it starts again from the top.

### Pitch

`pitch` is a whole number of semitones, 0 by default, and it is **independent of
`rate`**: the region lasts exactly as long as it did and sounds higher or lower.
Range ±24.

This is the one gesture with no cheap implementation. Web Audio has no pitch
shifter, and `playbackRate` is already spoken for by stretch. It needs a
granular shifter in an `AudioWorklet`: overlap-add short grains, resampled by
the pitch ratio, written by hand.

Its artefacts — a faint periodicity at the grain rate, smearing on transients —
are characterful on noise and texture and would be unacceptable on a voice or a
piano. This collection is noise and texture. If it sounds wrong, the fallback is
to say so plainly rather than to hide it behind a worse algorithm.

The gesture: take a region up, enter pitch by button, drag across its box. No
number, no semitone readout; the region's edge takes on a tint that runs one way
for up and the other for down.

### Playing the collage

A play/stop transport in the bar. Play schedules one buffer source per region
from its slice, starting at `now + at_s`, with `playbackRate = rate` and gain
at the region's `gain` (1.0 until a gain gesture exists). Stop silences
everything at once. A playhead line moves down the canvas as it plays — a
line, not a number. Regions may overlap in time across tracks; that is the
point of tracks, and the mix is a plain sum.

Slices are fetched for every region before play starts, so playback does not
stall on the network mid-piece. Fifteen regions is small; a collage with many
more should still start within a breath, and if it cannot, the transport says
it is still loading rather than starting late.

Play from a tapped point is not built here. Play starts at the top.

Only one mode is ever active. The default is trim, so a tap on a handle always
does the least surprising thing.

## The model

```jsonc
"collage": {
  "regions": [
    {
      "id": "r1",
      "hash": "fa30…",      // the source, frozen by the stored commit
      "track": 0,           // lane, left to right
      "start_s": 41.2,      // where the cut begins in the source
      "end_s": 47.9,        // internal only; never displayed
      "at_s": 12.0,         // when it sounds; internal only
      "rate": 1.0,          // stretch; 1.0 is untouched
      "gain": 1.0,          // linear, never displayed
      "fade_in_s": 0.0,
      "fade_out_s": 0.0
    }
  ]
}
```

Snipping a region produces two regions and deletes none of the source. Every
field that names a second is internal; the interface draws it as length or
position and never prints it.

## Playback

Regions are cut from sources that can be hundreds of megabytes, so the whole
file is never sent. The server slices the region to a small WAV
(`GET /api/files/{hash}/slice?start=&end=`), and the client decodes only that.
This is the one place client-side decoding is allowed, because the slice is
bounded by the region.

Stretch is a playback rate for now — varispeed, which shifts pitch. For noise
and texture that is usually the wanted sound. Pitch-preserving stretch is a
later decision, not a default.

### What stretch changes, and what it does not

Stretch changes `rate` and nothing else. The cut into the source — `start_s`
to `end_s` — is untouched, so the material is the same; it plays slower or
faster. A region's footprint in the collage's time is therefore
`(end_s − start_s) / rate`, and that is the height it draws at. Halving the
rate doubles the box; the cut inside it is unchanged.

The gesture, in the order the user gave it: tap a handle to select it, enter
stretch mode by button, then drag that handle. The other end stays anchored
and the box grows or shrinks from the dragged end, with the rate following.
In trim mode the same drag would move the cut; in stretch mode it moves the
rate. That is the whole difference, and it is why only one mode may be active.

Bounds: **0.25× to 4×** — two octaves each way. Past that varispeed stops being
a stretch and becomes a different instrument. Configurable beside the caps,
and the drag simply stops at the bound; nothing prints the number.

Playback uses Web Audio's `playbackRate` on the sliced buffer. The slice route
is unchanged: it still serves the source cut at 1×.

Regions reference sounds by hash, so a collage still resolves after files move.
A region may only reference a hash already in the project's frozen sound set;
collage cannot introduce new material, because `stored` was committed.

Several regions may cut from the same source, which is the normal case for a
sparse 15-minute recording.

## Finding material in a sparse source

Cutting a phrase out of a 15-minute speech recording needs navigation, and the
two analyses already built are exactly that:

- **Silence intervals** show where there is nothing, so 20 seconds of sound
  inside 293 seconds is visible at a glance.
- **YAMNet spans** tint speech, music and other, so the speech in a long
  recording can be found without scrubbing through it.

Both already exist and are already drawn on waveforms. This is the first place
they earn their cost.

## Commit freezes what this stage produced, not what comes after

Committing out of collage freezes the `collage` field: regions, placements,
rates and gains, canonically serialised and digested. Nothing is rendered.

This is a record of this stage's output. It is **not** a lock on the
arrangement. `enrich` copies the description forward into its own field and may
move, adjust and re-balance freely there. The `collage` field itself never
changes again, so its digest keeps meaning what it meant on the day it was
taken, while the work continues one field along.

Every stage owns its own artefact. Downstream stages read the previous one and
write only their own.

## `enrich` becomes the next placeholder

Collage cannot commit while it is the last column — that is the deadlock the
board currently reports. Building this view means `enrich` must exist as a
column with a cap of 1 and no view of its own, the same placeholder role
`collage` has held until now.

Each new view pushes the placeholder one step along. The pipeline is never
allowed to run ahead of the tools actually built for it.

## Constraints

- No route may delete audio. The two tests asserting this must keep passing.
- A region may only reference a hash in the project's frozen sound set.
- Sources differ in sample rate (44.1k and 48k) and channel count. Any preview
  render must resample and match channels.
- No seconds, no grid, no decibels, anywhere in the interface.
- Mobile matters, but cutting is fiddly on a phone. Say plainly if a surface is
  desktop-only rather than shipping something unusable one-thumbed.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [09-swipe.md](09-swipe.md)
- **next**: none.
