# Arrangement pipeline (prototype)

Scripts that made the HW002 arrangement experiments on 1 October 2026.
They are copied here from a scratch folder so they are not lost; paths are still hard-coded.
TODO.md tracks moving them into `hands` properly.

1. `arrange.py ID "a-b,c-d"` copies `HW002_121_full.als`, deletes every gap with Edit → Delete Time, restores automation state, and renders. Run it in `hands`.
2. `autostate.py` reads automated parameters during playback. `full_autostate.json` holds the uncut set's values at segment starts.
3. `verify.py ID "a-b,c-d"` trims the render, checks each bar against the full render, measures it, and writes the MP3. Run it in `ears/mlab` with `--with lameenc`.
4. `entries.py` builds /skrng manifest entries, and `batch.sh` runs a list of versions.

## 1 October, batch 3

- `arrange2.py` adds a two-bar lead-in, because the first ~0.9 s of every Live take is off the timeline.
- `verify2.py` trims the lead-in at a measured offset and runs a lag-based timeline check, calibrated to fail on a known-bad render. It also checks bars against the full render.
- `plan3.json` lists batch 3 and the batch-2 re-renders. `batch3.py` runs it with one retry per version.
- `build_site.py` builds the /skrng batches. Announcements are made with macOS `say` (Daniel) and padded to 500 ms of silence on each side.

## 1 October, batch 4

- `timeops.py`: Delete, Duplicate, Copy and Paste Time via the Edit menu. Each one is checked by `song.last_event_time`.
- `arrange4.py`: grid sections with repeats (a longer scoop), drop-out gaps pasted from a silent bar, and a two-bar lead-in.
- `hats.py`: rewrites perc 1 and perc 2 as stacked pad layers (A–E).
- `verify4.py`: trims at Live's own beat 0 (`<take>.timing.json` from `record_arrangement`). It checks the low band against `hw002_121_full_aligned.wav`, checks that gaps are silent, and measures the hat steps.
- `retrim.py`: moved batches 2–3 onto the grid. The old reference render had its beat 0 at 0.917 s, so every earlier trim started that much early.

## 2 October, batch 4.1

- `fx.py` makes clip-level edits on the set's own clips, so Anthony's warp settings are kept:
  - It lengthens the noise splash in place: unloop the clip, then set its end.
  - It copies the beatbox phrase once and stretches only its final "wuh", using one warp marker at the wuh's start and a later end. New clips made from the file are auto-warped at a guessed tempo, so it copies the original instead.
- `arrange41.py` and `verify41.py` extend batch 4 with those edits. The checks cover the splash-tail level against a bar without it, and the wuh's length and continuity.
- Fixed a reopen bug in `arrange.py` and `arrange4.py`: a retry found its version still open. Saving it overwrote the fresh copy, and the cuts ran twice. The code now switches to another set first.
- Live renames auto-named audio tracks when their clips change, so `fx.py` addresses tracks by index.

## 2 October, batch 4.2

- `fx.py` adds:
  - `phrase_at`, which puts the wuh's start on a grid point and sets its length in beats.
  - `tail_slices`, which copies the phrase's last 8th or 16th onto later grid points (the "chops").
  - `splash_copies`, which places the 3-beat splashes.
  - `break_level`, which sets the Break group fader in dB.
- `plan42.json` holds the batch:
  - Tracks 1–6: six grids for the wuh, the silence and the kick.
  - Track 7: the breakdown at −6 dB instead of −4.
  - Tracks 8 and 10: hats capped at three layers.
  - Tracks 9–10: track 1's early scoop.
- `verify42.py` measures the drop in four ways:
  - the drop's LUFS against the bar before the kick, and against the loudest breakdown bar;
  - the splash tail's gain;
  - the wuh's length and any dropouts;
  - each chop's onset error against the grid, with a tolerance of 40 ms. The beatbox's soft "w" reads 25–35 ms late.
- Results:
  - With the breakdown at −4 dB, the drop is only 0.4–0.9 LU above the loudest breakdown bar. At −6 dB it is 2.4 LU above.
  - Track 3's 16th chops failed twice: one chop measured 60 ms early. It was published with a note so Anthony can judge it by ear.
