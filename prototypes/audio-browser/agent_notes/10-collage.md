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

## The model

```jsonc
"collage": {
  "regions": [
    {
      "id": "r1",
      "hash": "fa30…",      // the source, frozen by the stored commit
      "start_s": 41.2,      // where the cut begins in the source
      "end_s": 47.9,        // internal only; never displayed
      "at_s": 12.0,         // when it sounds, relative to the collage start
      "gain": 0.8,          // linear, never displayed
      "fade_in_s": 0.1,
      "fade_out_s": 0.4,
      "note": ""
    }
  ]
}
```

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

## Commit freezes a description

Committing out of collage freezes the regions, their placements and their gains.
Nothing is rendered. The digest covers the description, canonically serialised.

`enrich` reads the description and works from the original sources, so the
arrangement stays editable downstream instead of being baked into a file that
cannot be taken apart.

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
