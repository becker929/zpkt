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
