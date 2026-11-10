# Job: render a one-shot pack from Anthony's own racks

## Purpose

The listening-test stimuli under `out/sweeps/` are entirely synthetic: a
clap made of noise bursts, a hat shaped by a decay parameter, a kick built
from a tone generator. `listen/realism_check.py` already exists to ask
whether those synthetic stimuli actually sit inside the measured
distribution of real one-shots (`out/library_real.csv`), and plenty of them
do not. This job gives the listening test a second, better source of
stimuli: real one-shots rendered out of Anthony's own Drum Racks and
instruments, isolated one hit at a time. These are not a replacement for
the synthetic sweep stimuli (which exist specifically to vary one parameter
at a time); they are a second pool of stimuli that are real sounds by
construction, to compare against.

This is an Ableton-side job only, reusing the same tap-and-record mechanism
as the multitrack bounce job and the sweep rig. It produces one wav and one
sidecar JSON per one-shot, plus a final realism check run on the whole
pack once it lands in the analysis repo.

## What a person must do by hand

- Point the job at one real set (same target-selection approach as
  PLAYBOOK section 1). Open a copy-on-write clone, never the original;
  never save it.
- Decide which pads and instruments in that set are worth capturing.
  Nothing here infers this automatically: a Drum Rack has 128 possible
  pads and most sets use a handful; a person (or an agent working from the
  pad/rack names and, ideally, listening to them) picks the ones that read
  as a distinct, usable sound.
- Assign each captured one-shot its `job` label from the fixed list below.
  This is a musical judgment call (is this one-shot a "stab" or an
  "impact"?), not something Live's API exposes. When it's ambiguous, say
  so in the sidecar's free-text field rather than guessing silently.
- Choose the MIDI note and note length per instrument where the default
  (see step 2) is not appropriate: a riser or pad instrument usually
  needs a longer held note than a one-shot drum hit does.
- After rendering, move the pack into the analysis machine (same manual
  "Drive folder" hand-off as the multitrack job) and run the realism
  check (step 5). Reading the result and deciding whether an
  out-of-range stimulus should be re-recorded, re-labelled, or kept
  anyway is a human call.

## What the rig does

### 1. Locate candidate instruments

Same offline-first approach as PLAYBOOK section 1: decompress the target
`.als` (`gzip -dc SET.als > /tmp/set.xml`) and look for `<DrumGroupDevice>`
racks and their pad chains, plus any `<MidiTrack>` carrying a single
instrument (Simpler, Wavetable, a plugin instrument) rather than a rack.
This shortlists candidates before Live is even open. Once the clone is
launched and Path B is confirmed, enumerate live for real: for a Drum Rack,
`song.tracks[i].devices[j].drum_pads[pitch].chains` gives the pad's own
device chain (the same LOM path already proven in HANDOFF.md's real-kick
work); for a plain instrument track, `song.tracks[i].devices` is the whole
chain.

### 2. Trigger and record: one MIDI note, fixed velocity, isolated tap

Reuse the exact tap-and-record mechanism from `run_sweep_stem.py`, not a
new one: route a capture audio track's input to the source track's output
(`ensure_capture_track()`), then create a short session clip on the source
track containing exactly one MIDI note, fire it, and arrangement-record the
capture track, the same as `bounce_stem()` already does. Isolation here
comes from what is triggered, not from soloing a Drum Rack pad: because the
session clip contains only the one note for the one pad or instrument being
captured, the source track's output during that pass is, by construction,
just that one sound; the same principle the sweep rig already relies on.

```python
# call 1: create the empty clip
song.tracks[SRC].clip_slots[0].create_clip(CLIP_BEATS); result = 'clip'
# call 2 (after a sleep): fill it with exactly one note
c = song.tracks[SRC].clip_slots[0].clip
c.name = 'oneshot_tmp'
notes = [MidiNoteSpecification(pitch=NOTE, start_time=0.0,
                                duration=NOTE_DURATION_BEATS,
                                velocity=VELOCITY)]
c.add_new_notes(tuple(notes)); c.looping = 0; result = 'notes'
```

Fixed velocity: use 100 (the same value the sweep rig's own example notes
use) unless the instrument is known not to respond meaningfully to
velocity, in which case note that in the sidecar rather than silently
picking a different number for no recorded reason.

Note duration and total capture length are job-dependent, and this is a
real difference from both the sweep rig and the multitrack job, which each
use one fixed bounce length. A kick, clap, or closed hat needs a short gate
and a couple of beats of tail; a riser, pad, or sustained impact may need a
long held note and many beats of tail to capture the full decay. Pick
`NOTE_DURATION_BEATS` and the total `bounce_beats` per instrument, not as a
single constant for the whole pack, and err long on the tail; a one-shot
with silence trimmed off the end afterward costs nothing, but a one-shot
whose decay was still ringing when the capture stopped is a bad row.

### 3. Naming convention

`<job>__<instrument-slug>__<index>.wav`, where `job` is exactly one of:

```
kick  rumble  hat_closed  hat_open  clap  perc  stab  pad  riser  impact
```

This matches the existing `out/sweeps/` naming pattern (`job__param__value`)
closely enough that `listen/realism_check.py` reads it correctly as-is: it
splits each filename on `__` and takes the first segment as the job. Keep
the job names exactly as spelled above; they are the same keys used in
`out/library_real.csv`, so a misspelled job silently drops out of the
realism check instead of erroring.

`instrument-slug` identifies the source the same way as the multitrack
job's track slug: lowercase, non-`[a-z0-9]` characters collapsed to a
hyphen (e.g. a Drum Rack pad named "Clap Layer 2" becomes `clap-layer-2`).
`index` is a zero-padded counter, unique within a given `job`, incrementing
across the whole pack; this is what disambiguates two different claps, or
two velocity/variant renders of the same instrument, without touching the
instrument slug.

### 4. The sidecar, per one-shot

One `<same-stem-name>.params.json` per wav, written only after the copy
succeeds; a wav without its sidecar is a dead row here exactly as it is
everywhere else in this rig. Required fields:

- `job`: the assigned label, one of the ten above.
- `instrument_slug` and `index`: as in the filename.
- `source_track_index`, `source_track_name`: where the sound lives.
- `drum_pad_note`: the pad's MIDI pitch if this came from a Drum Rack
  pad, else `null`.
- `device_chain`: the pad's or track's own device chain, same
  `{index, name, class_name, on}` shape as the multitrack job's sidecar.
- `midi_note`, `velocity`, `note_duration_beats`, `bounce_beats`: exactly
  what was sent and recorded.
- `tempo`: `song.tempo` at record time (mostly irrelevant to a one-shot's
  sound, but cheap provenance, and needed if `note_duration_beats` /
  `bounce_beats` are ever converted back to seconds).
- `sample_rate`: read back from the bounced wav file itself, same as the
  multitrack job (not queried from Live).
- `source_set`: the clone's `.als` path.
- `ambiguous_label`: free text, only present when the job assignment was
  a judgment call worth flagging (e.g. "could be perc or stab").
- `wav`, `timestamp_utc`: bookkeeping.

### 5. Check the pack for realism

`listen/realism_check.py` is already written and does exactly this
comparison; this job does not reimplement it. Run it from the
`sound-function` repo root once the pack has been copied onto the analysis
machine:

```bash
cd /home/user/sound-function
python3 listen/realism_check.py --json out/listen_realism_livepack.json
```

One real constraint to know before running it: the script has no directory
argument. It hardcodes its input to `out/sweeps/*.wav` and its reference
distribution to `out/library_real.csv`. To check this pack, its wav files
need to actually be sitting in `out/sweeps/` when the script runs; either
copy them there directly (the `job__instrument-slug__index.wav` naming
will not collide with the existing `job__param__value.wav` synthetic
stimuli, since the second segment differs in kind) or copy the whole repo
to a scratch location first if mixing real renders into the permanent
`out/sweeps/` pool is not wanted yet. `wav.stem.split("__")[0]` is the only
part of the filename the script actually reads, so anything after the
first `__` is free-form as far as the check is concerned; the fuller
convention above is for the sidecar and for a human scanning the directory,
not a requirement of this script.

The script's report scores each stimulus's `attack_ms`, `decay_ms`,
`crest_factor_db`, `spectral_centroid_hz`, `band_sub_share`, and
`band_high_share` against the p10-p90 band of real one-shots of the same
`job` from `out/library_real.csv`, and writes a JSON summary plus a
per-stimulus breakdown, printed to the console as well. Since these
stimuli are themselves real one-shots (not synthetic ones), a well-chosen
render from this pack should mostly land inside the real p10-p90 bands
by construction; one that does not is worth a second listen; it may be an
outlier real sound worth keeping anyway, a mislabelled job, or a capture
that clipped or truncated.

### Resumability

Same rule as everywhere else in this rig: before rendering a one-shot,
check whether both its wav and sidecar already exist; skip if so.

### Path-B crash rules (non-negotiable, quoted from `HANDOFF.md` section 7)

> - Never read a param in the same call you wrote it. Write, then read.
> - One device, <= 20 params per call. No giant sweeps in one call.
> - Sleep ~0.3s between browser loads. One VST load per call.
> - Stay under 12s per call. Keep sleeps <= 0.5s.
> - After track create/delete, re-fetch `song.tracks[i]` (alias goes stale).

Loading several different Drum Rack pads' chains in sequence to inspect
them is exactly the "one VST load per call, sleep between browser loads"
case the rules call out; do not try to enumerate many pads' plugin devices
in one call. And the general safety rules from `HANDOFF.md` section 15 and
PLAYBOOK section 9 apply here without exception: COW clone only, never
saved; restore anything this job changes (mainly the temporary session
clip and the capture track's routing/arm state, cleaned up the same way
`run_sweep_stem.py` disarms its capture track in its `finally` block);
never restart or quit Live with unrecovered render progress; prefer
OSC/text over screenshots.

## Ownership: this pack is different from corpus audio

Every wav this job produces is Anthony's own performance of his own
instruments, rendered by his own rig. He owns it outright and can publish
it, share it, or use it however he likes; there is no redistribution
restriction on it, unlike the corpus audio measured elsewhere in this
project. That corpus audio is either released tracks under a permissive
licence that still does not extend to redistributing the audio itself, or
(per `stems-request.md`) stems producers shared privately on the explicit
condition that the audio stays private and only measurements get
published. Do not conflate the two. A sidecar or manifest entry for this
pack should not carry any of the "must not redistribute" language that
applies to corpus stems, because it does not apply here.
