# Arrangement pipeline (prototype)

Scripts that made the HW002 arrangement experiments on 1 October 2026.
They are copied here from a scratch folder so they are not lost; paths are still hard-coded.
TODO.md tracks moving them into `hands` properly.

1. `arrange.py ID "a-b,c-d"` copies `HW002_121_full.als`, deletes every gap with Edit → Delete Time, restores automation state, and renders. Run it in `hands`.
2. `autostate.py` reads automated parameters during playback. `full_autostate.json` holds the uncut set's values at segment starts.
3. `verify.py ID "a-b,c-d"` trims the render, checks each bar against the full render, measures it, and writes the MP3. Run it in `ears/mlab` with `--with lameenc`.
4. `entries.py` builds /skrng manifest entries, and `batch.sh` runs a list of versions.
