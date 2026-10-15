# Sound in zpkt's pages: rendered files only, through one player

## The rule

**The browser never does the DAW's job.** No page, demo, prototype, mock-up or test page may synthesize or change
audio in a way that belongs in the DAW: no synths or drum machines, no EQ or filters, no compression, distortion or
clipping, no reverb or delay, no panning or width, no gain moves standing in for a mix move, no granular, slicing,
time-stretch or pitch-shift, no collage or arrangement assembled from pieces. Nothing that sketches what a change
"would" sound like. Anthony decided this on 14 October 2026 after the HW002 lab (`docs/lab.md`): its stand-ins for
COLDFIRE, the Decapitator, Supermassive and the rest sounded plausible and were wrong, and a sound that is plausible
and wrong fools him. That is worse than no sound at all.

**Music in zpkt's demos comes only from the player engine** (below). It plays files that were rendered, as they were
rendered. Every change you hear is a different file, or a different place in one file.

**What Web Audio is for.** Web Audio is the player engine's way to the speaker (not `<audio>` elements, which cannot
switch on the bar). These uses are allowed, because none of them does the DAW's job:

- **Playing rendered files**: decoding, starting, stopping and jumping on the audio clock, and the few-millisecond
  fades a switch needs so it does not click.
- **A loudness match for comparing** two renders (studio's Match loudness): a listening aid, not a mix move.
- **The mic**: capture, levels and sending it to the Mac.
- **Interface sounds** that are not music, such as studio's ready sound.

**No other use, even if Anthony asks for it.** If he asks or insists, an agent does not just do it. It first changes
this document and every document that repeats the rule, as narrowly as the request needs: one named exception, for
one page, with its reason and date. Then it builds what was asked, and nothing beyond that exception. A request is
never read as lifting the rule in general.

Where the files come from: a change to a set is heard only as a render of that set from Live. Other material is
played as the file it is: library sounds, collages made on the Mac, and the background work in The Wasteland
(`docs/studio-agent.md`). Each file is labelled with where it came from, so a sketch is never taken for the set.

What the rule does not cover:

- **The visual and tactile side stays.** The lab's knobs, faders, pads, 3D pieces, haptics and animations are worth
  keeping. Only their sound goes.
- **Measuring is not making sound.** Meters, spectra and waveforms drawn from rendered files, or from numbers
  computed on the Mac (`ears`), are fine.

## Uses already in the repo

As of 14 October 2026. Nothing was changed when the rule was written; what breaks it is replaced when its page next
gets work, and never copied.

| Where | What it does | Status |
|---|---|---|
| `studio/static/lab/` (the HW002 lab) | Stems through channel strips, sketches of every kick and mix param, a kick synth, granular and slice players | Breaks the rule. Its sound is replaced by the player engine; its surfaces stay. |
| `studio/static/js/audio.js`, `clip.js`, `options-clip.js`, `buffers.js` | Plays speech and renders on the audio clock; options switch with short fades and a loudness match | Allowed: this is the player engine's seed. |
| `studio/static/js/cue.js` | The ready sound: two notes made with oscillators | Allowed: an interface sound, not music. |
| `studio/static/checklist/flow/sound.js` | The check's click: a filtered noise tick and a short tone, about 60 ms | Allowed: an interface sound, not music. |
| `studio/static/js/mic.js` | Captures the mic through an AudioWorklet | Allowed: the mic. |
| `prototypes/audio-browser/frontend/lib/` (`collagePlayer.ts`, `slicePlayer.ts`, `softClip.ts`) | Assembles a collage from slices and soft-clips it | Breaks the rule (assembly and clipping); to be replaced if the prototype is revived. |

## The player engine

The engine moves between renders, so it can only play states that exist as audio. A control therefore has two
kinds of position: **audible** (a render of that state exists and is loaded) and **not yet audible** (no render
yet, or one still on its way). The engine's whole job is to make that difference impossible to miss.

### Where the sound comes from

Two layouts, chosen per surface:

1. **Many files.** One render per state (an option, a step on a macro, a knob value). The engine switches between
   them on the bar clock, at the same place in the bar, so a switch never jumps in the music. This is what
   `options-clip.js` already does for studio's options.
2. **A sprite atlas.** One long render holding every state back to back, each the same number of bars, with an
   index of where each state starts. The engine jumps around in the one file. One fetch, one decode, and every
   state that exists is ready at once. Good for a grid of variants rendered in one batch (a pack render).

In both, a state's audio is exactly what Live rendered: level matching, if a comparison needs it, is done at render
time (a second file at the matched level), not with a gain in the browser.

The engine plays through Web Audio, on the audio clock: buffer sources started and stopped at sample-exact times,
with only the short fades a switch needs. `options-clip.js` is its seed. Not `<audio>` elements: they cannot jump on
the bar (tens of milliseconds of jitter), and iOS limits how many play at once.

### Controls: not yet audible

A control whose current position is not yet audible must say so, in a way the eye catches without reading:

- **Ghosts.** The knob or fader draws the new position as a ghost (outline, translucent, breathing slowly) while
  the solid indicator stays where the sound still is.
- **Dotted lines.** The path from what you hear to what you asked for is dotted, on the control and on the player's
  waveform (where the change will land in the bar).
- **Colour intensity.** A pending control pulses between its colour and a dim version of it, slow and steady, so a
  page with several pending changes shows them all at a glance.
- **What it is waiting for.** A render being made (with the queue position when there is one), a file loading, or the
  next bar. The three look different: a render in progress is the slowest pulse; a loaded file waiting for the bar
  ticks with the beat.

### Controls: it just became audible

The moment the new state actually reaches the speaker (not when it was requested, not when it loaded), two layers of
response fire together:

- **At the control.** A click (a haptic tick where the phone has one) and a white ring, layered (two or three rings a
  few frames apart), that expands from the control and fades out. The ghost snaps into the solid indicator.
- **Across the player.** A brief, fairly intense effect over the whole player at once: a diagonal flash of light
  that sweeps the surface, the outline and the waveform; the player's colour shifts to the new state's colour and
  settles. It reads as "the sound changed" even out of the corner of the eye.

Both are timed to the audio, not to the tap. If the change lands on the next bar, the flash lands on the next bar.

### What this means for designing surfaces

- **A surface can only offer what has been rendered.** A continuous knob becomes a set of rendered stops; between
  them it shows a ghost and, if asked, queues a render. Sweeps and pack renders (`hands`) are how the stops get made.
- **The reference space decides what to render** (`docs/studio-agent.md`): a bounded region around the references'
  measurements, plus about 10 % of renders beyond it on purpose. Renders are spent where Anthony is likely to play.
- **Speed comes from rendering ahead.** The engine is only as quick as the renders behind it, so the agent renders
  the likely next states while Anthony listens to the current one.
