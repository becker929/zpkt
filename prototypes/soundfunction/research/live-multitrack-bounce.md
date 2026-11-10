# Job: bounce a real multitrack from Ableton Live

## Purpose

Every "multitrack" the corpus has measured so far is not actually a
multitrack. `corpus2/band_pump.py` reads `stems/<id>/drums.wav` and
`bass.wav`, which are Demucs's guess at separating a finished, mastered
release into four buses. Demucs bleed and separation error are baked into
every pump number in `knob-map.md` and every band-share number derived from
those stems. This job replaces one of those guesses with the real thing: it
opens one of Anthony's actual Ableton sets and bounces every live track as
its own isolated stem, so the lab measures a kick, a bass, a rumble and a hat
that were never blended and un-blended by a neural separator. It reuses the
Ableton rig documented in `HANDOFF.md` and `PLAYBOOK_skill.md` in this
folder; it does not add a new control mechanism to Live.

This is an Ableton-side job only. It produces audio and sidecar JSON. It does
not run any measurement itself; the lab (`lab/runner.py --local` and
`corpus2/`) ingests the output afterward, out of band, exactly as the sweep
seam already works.

## What a person must do by hand

- Point the job at one real `.als` project (see PLAYBOOK section 1 for how
  to shortlist one by size and offline XML inspection). This is a judgment
  call about which set is rich and finished enough to be worth the render
  time; the rig does not choose the target itself.
- Confirm Live is not already running, and that Path B (`AbletonLiveMCP` on
  TCP 16619) is the active control surface, per HANDOFF section 8.
- After the bounce finishes, move the output folder from the Mac into
  whatever shared location feeds the lab's `--local` ingestion (the
  "Drive folder" already used for single-track exports per
  `live-experiments.md`'s Plumbing section). That copy is a manual step;
  nothing here reaches across machines on its own.
- Decide whether a track that looks empty, disabled, or bypassed is actually
  worth skipping, in the borderline cases the automatic skip rules below
  don't cleanly catch (a group/folder track with its own audible bus
  processing, for instance). The rig applies a mechanical rule; a person
  should sanity-check the resulting stem list before treating it as
  final.

## What the rig does

Clone, enumerate tracks, tap and record each surviving track exactly the way
`run_sweep_stem.py` already taps and records one instrument, write one
sidecar per stem, and skip anything already rendered on a re-run.

### 1. Open the set (copy-on-write clone, never saved)

Exactly the PLAYBOOK's clone step. Never open the artist's real file.

```bash
mkdir -p "/Users/anthonybecker/_agent_scratch"
cp -Rc "/Users/anthonybecker/_tmsmsm/.../PROJECT_FOLDER" \
       "/Users/anthonybecker/_agent_scratch/PROJECT_FOLDER"
open -a "Ableton Live 12 Suite" \
     "/Users/anthonybecker/_agent_scratch/PROJECT_FOLDER/THE_SET.als"
```

`cp -Rc` on APFS is instant and copy-on-write, so edits to the clone cannot
touch the original even on a crash. Poll for Path B the same way PLAYBOOK
section 3 does (`nc -z 127.0.0.1 16619` in a loop), then confirm the set
actually loaded (`song.tempo`, `[t.name for t in song.tracks]`). Once open,
never call `save_song` or any equivalent, and never quit Live once real
render progress exists that hasn't been copied out yet.

### 2. Enumerate tracks, apply the skip rules

Walk `song.tracks` (0-based, as the PLAYBOOK's offline XML note confirms:
track order in the `.als` matches `song.tracks[i]` exactly). `song.tracks`
never contains the master track or return tracks in the first place: those
live in `song.master_track` and `song.return_tracks` and are never touched
by this job. Beyond that, skip a track when any of these hold:

- **Muted.** `track.mute == 1`. A track the artist muted is not part of the
  set as heard; do not resurrect it as a stem.
- **Empty.** No arrangement content (`len(track.arrangement_clips) == 0`)
  and nothing in its session slots either. There is nothing to record.
- **A group/folder track.** A group sums its children's output through its
  own device chain; each child is already captured on its own. Recording
  the group too is a redundant post-group-bus sum, not a new instrument.
  If the group applies its own audible processing that actually matters
  (a bus compressor gluing the drums, say), that is a real limitation of
  the per-leaf-track approach; flag it rather than silently including or
  excluding the group without a note.

Do not skip a track just because it looks quiet or minor from its name;
the point of this job is to see what is really there, including layers a
person might not think to ask for individually.

### 3. Per-track tap and record (reuse `run_sweep_stem.py`'s mechanism)

This is the same technique the sweep rig already proved, not a new one.
Reuse a single capture audio track, re-routed to a different source per
pass, exactly like `ensure_capture_track()` in `run_sweep_stem.py`:

```python
# one call: route the capture track's input to listen to the source track's
# own output, arm it, and start monitoring
tr = song.tracks[CAPTURE_IDX]
rt = next(r for r in tr.available_input_routing_types
          if r.display_name == SOURCE_TRACK_NAME)
tr.input_routing_type = rt
tr.arm = 1
tr.current_monitoring_state = 1
result = tr.input_routing_type.display_name
```

Only stereo channels are offered for this routing, same as the sweep rig;
that is fine because the measures the lab computes on stems (band shares,
crest, sidechain depth) are gain-invariant, so a post-fader tap is valid.

**One real difference from the sweep rig, deliberately:** `run_sweep_stem.py`
fires a synthetic session-clip loop on the source track so a single
isolated pattern repeats under the tap. This job does the opposite on
purpose: it plays the set's own arrangement, start to finish, once per
source track, because the point is to capture the real performance
(the real fills, the real automation, the real interaction with whatever
triggers a sidechain), not a repeated test pattern. Before each pass, set
`song.loop = 0` and `song.current_song_time = 0.0`, then
`song.start_playing()` and `song.record_mode = 1` on the capture track,
exactly like `bounce_stem()` in `run_sweep_stem.py`, but sized to the whole
arrangement length rather than a fixed `bounce_beats`. Read the arrangement
length once (e.g. `song.last_event_time`, confirmed live before relying on
it) and sleep for that many beats converted to seconds at `song.tempo`, plus
the same settle margin the sweep rig uses. Stop, `song.record_mode = 0`,
`song.stop_playing()`, then copy the recorded clip's `file_path` out as
`bounce_NNN.wav`, identically to `bounce_stem()`.

One caveat carried over from HANDOFF section 11: on this machine,
arrangement playback has intermittently rendered silent on freshly created
or heavily churned audio tracks, which is exactly why the sweep rig avoided
it and used a session-clip loop instead. This job cannot avoid arrangement
playback: the real content only exists there, so treat a near-silent
capture on a track that visibly has content in its arrangement clips as
this known failure mode, not a routing mistake, and retry the pass (a Live
restart has cleared it before). Setting `song.back_to_arranger = 0` before
each pass is a cheap defensive step against the related fix noted in
`hands/src/hands/recorder.py`.

Because each pass plays the whole song in real time (there is no proven
faster-than-realtime bounce path on this rig), total render time is roughly
song length times surviving-track count. That is a real cost of reusing the
proven mechanism rather than inventing a parallel-capture scheme; accept it
and lean on resumability (below) rather than trying to record several
tracks in one pass.

### 4. Track name to output filename

Each stem's filename is `<track-index>__<track-name-slug>.wav`, zero-padded
to two digits on the index, e.g. track 6 named `Kick (G)` becomes
`06__kick-g.wav`. The slug is the track name lowercased, with anything that
is not `[a-z0-9]` collapsed to a single hyphen. The index guarantees
uniqueness even when two tracks share a name (Anthony has done this); the
slug keeps the filename legible without opening the sidecar.

Land the whole set's stems in one folder per song, because that is exactly
the layout `lab/runner.py --local`'s `run_local()` expects for a multitrack
item: a folder under `stems/<song-slug>/` holding one audio file per track.
It does not care about the exact filename beyond the audio extension check,
so this convention is a readability choice, not a hard requirement of the
ingesting code; keep it anyway, because the report labels each row with
the file's name verbatim.

### 5. The sidecar, per stem

One `<same-stem-name>.params.json` per wav, written only after the copy
succeeds (a wav without its sidecar is a dead row, exactly per the seam
rule in `HANDOFF.md` section 6 and `sweeps_README.md`). Required fields:

- `track_index`: the 0-based `song.tracks[i]` index.
- `track_name`: the exact Live track name at bounce time.
- `device_chain`: a list of `{index, name, class_name, on}` for every
  device on the track, in order, read the same way PLAYBOOK section 4
  already reads a device chain (`d.name`, `d.class_name`,
  `d.parameters[0].value` for the On/Off state). This is a summary for a
  human reading the sidecar later, not something the lab parses.
- `tempo`: `song.tempo`, read once per set (it is global, not per-track).
- `frozen`: `track.is_frozen`.
- `muted`: `track.mute` (always `false` here, since muted tracks are
  skipped in step 2; recorded for completeness, not as a filter signal).
- `sample_rate`: read back from the bounced wav file itself after the
  copy (e.g. `soundfile.info(path).samplerate`), not queried from Live.
  Live's engine sample rate is not part of the proven Path-B surface this
  rig has exercised; reading the file that was actually written is the
  honest source of truth here.
- `wav`: the filename from step 4.
- `source_set`: the clone's `.als` path, for provenance.
- `capture_track`, `arrangement_length_beats`, `timestamp_utc`: bookkeeping,
  same spirit as `run_sweep_stem.py`'s sidecar.

There is no `measure` field to fill here the way a sweep sidecar has one;
this job's contract ends at wav+sidecar. Measurement happens later,
out-of-band, in the lab.

### 6. Resumability

Before recording a track, check whether both `bounce_NNN.wav` and its
`.params.json` already exist for that track index; if so, skip it, log the
skip, and move to the next track. This is the same resumability
`run_sweep_stem.py` already has for sweep rows, applied per track instead
of per sweep step. A crash partway through a 20-track set should cost at
most the one track that was mid-render, not the whole job.

### 7. Path-B crash rules (non-negotiable, quoted from `HANDOFF.md` section 7)

> - Never read a param in the same call you wrote it. Write, then read.
> - One device, <= 20 params per call. No giant sweeps in one call.
> - Sleep ~0.3s between browser loads. One VST load per call.
> - Stay under 12s per call. Keep sleeps <= 0.5s.
> - After track create/delete, re-fetch `song.tracks[i]` (alias goes stale).

The per-track loop in this job does not create or delete tracks after the
one capture track is set up, so the last rule mainly matters if a track
turns out to need to be skipped mid-run for a reason discovered live (a
disabled routing option, say) and the enumeration has to be redone.

And the general safety rules from `HANDOFF.md` section 15 and PLAYBOOK
section 9 apply without exception: work only on the COW clone, never save
it; restore any parameter this job changes (it changes none on the source
tracks themselves, only the capture track's routing/arm state, which should
be disarmed at the end exactly like `run_sweep_stem.py` disarms it in its
`finally` block); never restart or quit Live with unrecovered render
progress; prefer OSC/text over screenshots.

## What this unlocks

This directly settles the open question in `live-experiments.md`'s E1 and
the standing verdict on **H34** in `research/hypotheses.md`: currently
"not supported" (median sub-minus-low pump on the Demucs-separated bass
stem is -0.2 dB, essentially flat), without needing Demucs at all. E1 as
written still tests this synthetically (build a loop, render two variants,
separate both with Demucs, compare). This job gives the other half of that
comparison for free: a real kick and a real bass/rumble track from an
actual released-quality arrangement, tapped whole and never blended by a
separator, feeding `report_multitrack`'s own `sidechain_between()` measure
directly. If the split duck shows up clearly here but not in the
Demucs-separated corpus numbers, H34's "not supported" verdict is a
separator artifact, not a fact about the genre; the register should say
so explicitly. If it does not show up here either, on Anthony's own
untouched kick and bass, that is real evidence the technique is rare or
absent in practice, not just hidden by Demucs.

Beyond H34 specifically, this is the first true multitrack the whole
project will have measured. Every other "multitrack" number anywhere in
`corpus2/` is a Demucs guess at what a finished mixdown's stems probably
were. This job gives a ground truth to check those numbers against: for
at least one set, it answers whether separator bleed is inflating or
deflating the pump-depth numbers that every other measure in `knob-map.md`
and the corpus register currently treats as given. It also gives a real
instance of **H28** (kick and rumble sharing one layer versus two separate
ones) read directly off the actual track list, rather than inferred from a
bass-stem proxy, and a real, non-synthetic comparison point for E3's
"kick body under the rumble" question: a genuine kick track next to a
genuine rumble track in the same set, at whatever relative level Anthony
actually mixed them, rather than a level chosen for the synthetic test.


## Amendments after the first two runs (2026-09-12)

1. **Size each bounce from the source track's own clips, never from
   `song.last_event_time`.** The latter is the last event anywhere in the set
   and produced stems that were 57% silence. Use the end of the track's last
   `arrangement_clip` plus the settle tail.
2. **Any two-take comparison must be aligned before use.** Real-time takes
   start a few hundred samples apart. Align by cross-correlation with the lag
   search constrained to under half a beat; an unconstrained search returns
   one whole beat. `lab/duck_calibration.py bypass` does this itself now.
3. **Some plugins expose no parameters to the Live API.** LFOTool shows only
   on/off and stores its state as an opaque blob in the .als. When the spec
   asks for parameter values and they are not readable, say so in the
   sidecar, as the rumble sidecars do, rather than leaving the field blank.
4. **Tap pre-group.** When the track sits inside a group with nonlinear
   devices, route the track's own output to the capture track. Soloing and
   rendering the master pushes the take through processing that reacts
   differently to different inputs and contaminates any A/B.
