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
5. **The rest of the sounds.** Once 1–4 exist, adding the other fourteen is the
   same gestures again.

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
