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
