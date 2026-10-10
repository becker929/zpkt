# live_multitrack_bounce_v1 — real, unseparated multitrack stems

Job: `research/live-multitrack-bounce.md` / `specs/multitrack_bounce.job.json`.
Two of Anthony's real Ableton sets, opened as copy-on-write clones (never
saved over the originals), bounced track-by-track to isolated per-track WAV +
`.params.json` sidecars. This is a TRUE multitrack: every stem was tapped or
rendered from its own Live track directly, never separated by Demucs or any
other neural source separator.

Purpose: settle whether "duck the sub deeper than the low band" (H34) is a
real production technique the corpus's Demucs-based measurement was hiding,
or a genuinely rare/absent technique. `HW002/kick` (track 2) and
`HW002/rumble` (track 3) are the direct test of this — a real kick and real
sub/rumble layer from the same set, never blended and un-blended by a
separator. They were bounced first, before any other track, so the job would
still answer the core question even if it died partway through.

## Sets used

- **SNTS Style track 2026-04-21** — clone of
  `/Users/anthonybecker/_tmsmsm/daw-library/experimental projects/SNTS_4-22/SNTS Style track 2026-04-21.als`,
  opened at `/Users/anthonybecker/_agent_scratch/SNTS_4-22/SNTS Style track 2026-04-21.als`.
  Tempo 160 BPM. 44 original tracks (before an agent-added capture track).
- **HW002_14** — clone of
  `/Users/anthonybecker/_tmsmsm/Active Tracks/HW002/HW002_14.als`, opened at
  `/Users/anthonybecker/_agent_scratch/HW002/HW002_14.als`. Tempo 160 BPM. 18
  original tracks (before an agent-added capture track). Chosen as the
  largest/most-developed non-backup `.als` under that project folder.

Neither original `.als` file was ever opened directly or saved; only the
clones under `_agent_scratch/` were touched, and those clones were never
saved either (each stem was captured from a live, in-memory, unsaved Live
session).

## Track list: SNTS Style track 2026-04-21 (44 tracks, 0-based)

| idx | name | status | reason |
|---|---|---|---|
| 0 | Ref tracks | skip | group/folder track |
| 1-5 | Ref 2, Ref 3, Ref 4, Ref 5, Ref 1 | skip | muted |
| 6 | Kick (G) | **bounced** | priority kick track |
| 7 | Perc | skip | muted |
| 8 | Perc (pitched down) | **legitimate skip** | its instrument (a Drum Rack) was deleted from the project on 2026-04-06; see note below |
| 9 | Vol boost | skip | group/folder track |
| 10 | Kick layer | skip | muted |
| 11 | Pad layer | **bounced** | |
| 12 | Noise pad | skip | muted |
| 13 | Dry | skip | muted |
| 14 | Main pad | **bounced** | |
| 15 | Reverb | skip | muted |
| 16 | Bass SFX | skip | muted (the one candidate "bass/rumble" track in this set — muted, so excluded per the job's own rule; this set contributes no bass/rumble stem) |
| 17 | 18-Bruce Sterling - Fantasy prototypes and real disruption | skip | muted |
| 18 | Trash | skip | group/folder track (also muted) |
| 19-20 | 20-zapmachine, 21-wind2 | skip | muted |
| 21 | Pad (group) | skip | group/folder track |
| 22 | Pad (wind) | **bounced** | |
| 23 | Pad (hollow) | **bounced** | |
| 24-25 | 25-waterfall2, 26-waterfall1 | skip | muted |
| 26 | 27-warn3 | **bounced** | |
| 27-42 | 28-turretrot2 .. 43-Serum 2 | skip | muted (16 tracks, a large muted SFX bank) |
| 43 | 44-Audio | skip | muted AND empty |

6 tracks bounced, 1 legitimately skipped for a confirmed structural reason
(no wav produced), 37 skipped for the mechanical rules (4 groups, 33
muted/empty; some muted tracks also had real content that was never heard,
per the job's own rule that a muted track is not part of the set as heard).

## Track list: HW002_14 (18 tracks, 0-based)

| idx | name | status | reason |
|---|---|---|---|
| 0 | 1-01 - Lethal Storm | skip | muted (reference track) |
| 1 | kick group | skip | group/folder track |
| 2 | kick | **bounced** | priority kick track |
| 3 | rumble | **bounced** | priority bass/rumble track — sibling of `kick` inside `kick group`, i.e. a real H28/H34 kick+rumble pair from one set |
| 4 | perc group | skip | group/folder track |
| 5 | 6-2022-05-30-005 | **bounced** | |
| 6 | perc 1 | **bounced** | |
| 7 | perc 2 | **bounced** | |
| 8 | SFX group | skip | group/folder track |
| 9 | 10-ARC RAIDERS - Bastion Encounter | **bounced** | |
| 10 | 11-Audio | skip | empty (no arrangement or session content) |
| 11 | 12-2022-06-02-001 [2026-05-25 092256] | **bounced** | |
| 12 | Break group | skip | group/folder track |
| 13 | 14-ARC RAIDERS - Bastion Encounter | **bounced** | |
| 14 | 15-2023-11-14_bodhi-anthony-tech-01_9_stems_sound 4_ synth | **bounced** | |
| 15 | 16-2023-11-14_bodhi-anthony-tech-01_1_stems_sound 1_ synth horn-001 | **bounced** | |
| 16 | 17-2023-10-07-09-20 | **bounced** | |
| 17 | 18-beatbox | **bounced** | |

12 tracks bounced, 6 skipped (4 groups, 1 muted, 1 empty).

## Folders

- `snts-style-track/` — 6 stems (+ 1 legitimately-skipped track, no wav), ~726 MB.
- `hw002/` — 12 stems, ~1.8 GB.
- Total: 18 stems, ~2.5 GB.

Each stem is `<track-index>__<slug>.wav` + a matching `.params.json` sidecar
(`track_index`, `track_name`, `device_chain`, `tempo`, `frozen`, `muted`,
`sample_rate` read back from the wav, `wav`, `source_set`, `capture_track`,
`arrangement_length_beats`, `timestamp_utc`). No `measure` field — measurement
is out-of-band, same seam as the knob-sweep rig.

## Capture method

Two mechanisms were used, both reusing the proven `run_sweep_stem.py` tap
concept but adapted to play the set's OWN arrangement once per track (not a
synthetic loop):

1. **Real-time tap** (`sweeps/bounce_multitrack.py`): route a spare audio
   track's input to the source track's direct output, arrangement-record the
   whole set once per source track. Used for all 18 bounced stems.
2. **Native offline export** (Live's own Export Audio/Video, "Rendered
   Track" = the exact source-track name, via
   `~/.agents/skills/ableton-live-control/scripts/export_audio.applescript`).
   Used only for SNTS track 8, after the real-time tap repeatedly returned
   digital silence for that one track (see note below) — this method renders
   offline (seconds, not real-time minutes) and bypasses the custom routing
   entirely, using Live's own solo-render path, so it double-checks the
   real-time method's result rather than replacing it everywhere.

## Known caveats / things that fought us

- **A Hammerspoon config was intermittently interfering with Live**
  (confirmed and fixed by Anthony mid-run). Before the fix it caused: (a)
  periodic "Saving is not possible while recording" + stale crash-report
  dialogs that could block Live's main thread, and (b) REAL audio dropouts
  baked into a handful of takes (not just cosmetic dialogs). Affected tracks
  were identified by a duration/dropout integrity check, deleted, and
  re-bounced after the fix: `hw002/02__kick`, `03__rumble`,
  `05__6-2022-05-30-005`, `06__perc-1`, `07__perc-2`,
  `09__10-arc-raiders-bastion-encounter`,
  `11__12-2022-06-02-001-2026-05-25-092256`; `snts-style-track/08__perc-pitched-down`
  (see below). Everything in this archive was re-verified clean (or, for
  track 8, confirmed as expected content) after the fix.
- **The integrity checker flags several tracks with an apparent "dropout"**
  (a stretch of near-silence flanked by louder audio), e.g.
  `hw002/02__kick.wav` around 122-144s. These were CONFIRMED GENUINE
  arrangement content, not corruption: re-recording the same track
  independently reproduced the identical silent window to within ~2s both
  times, which a random technical glitch would not do. Read as a real
  breakdown/quiet section in the arrangement, not a capture defect.
- **`snts-style-track` track 8 ("Perc (pitched down)") is a legitimate
  skip, not a capture bug — no wav produced.** Two independent capture
  methods (real-time tap and native offline export) both correctly returned
  digital silence (~-138 dBFS). Root cause, confirmed by diffing 25
  auto-saved `.als` backups (read-only, never touching the live file): the
  track's instrument (a native `DrumGroupDevice` / Drum Rack) was deleted
  from the project on 2026-04-06 (present through the 23:22:56 backup,
  absent from the 23:41:03 backup onward, including this 04-21 working
  copy). The remaining 6 devices on the track are all audio effects with
  nothing feeding them. This means the track has been silent in Anthony's
  own working set since that edit, not just in this bounce. Confirmed with
  Anthony directly; see
  `snts-style-track/08__perc-pitched-down.SKIPPED.json` for the full
  evidence trail. Do not attempt to "fix" or restore this track.
- **The Mac went to sleep/locked once mid-session**, which froze Live's
  transport (`song.is_playing` stayed `True` but `song.current_song_time`
  stopped advancing, with no error surfaced) and produced one confirmed
  false "silent bounce" failure. Detected by comparing `current_song_time`
  across two reads; fixed by waking the Mac and, for later long real-time
  bounces, wrapping the runner in `caffeinate -dis` to prevent recurrence.
  Worth adding to the job spec as an explicit caveat: a "silent bounce" on
  this rig can mean the machine slept, not that the routing is wrong.
- **`bounce_multitrack.py`'s `arrangement_beats` (`song.last_event_time`)
  drifted slightly (a few beats) across separate script invocations** of the
  same Live session, because it was re-queried at the start of every
  invocation before the previous invocation's leftover capture-track clip
  (which slightly overshoots the real content, by the settle-tail margin)
  was cleared. Practical effect: stems from later invocations have a couple
  extra seconds of harmless trailing tail versus the true arrangement length
  (see each folder's duration spread above). Fix for next time: measure
  `arrangement_beats` once, up front, and pass it as a fixed value to every
  invocation rather than re-deriving it live.

## Do not

Do not treat this archive as uploaded/shared anywhere else. It was prepared
locally on Anthony's Mac for local hand-off only.
