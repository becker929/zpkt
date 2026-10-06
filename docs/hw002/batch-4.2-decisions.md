# HW002 batch 4.2: decisions and structural changes (5 October 2026)

From Anthony's review of batch 4.2 on /skrng. Written by Claude Code.

**Status (6 October 2026):** applied in batches 4.3 (splashes) and 4.4 (hats), published on /skrng
(site PR #46). Scripts: `hands/scripts/arrange_prototype/` `plan43.json`, `plan44.json`,
`arrange43.py` (adds `keep`), `run_batch.py`, `build_batch43_44.py`. Anthony confirmed 4.3 and 4.4
as the next steps; the voice-over rules below were applied as drafted.

## Structural changes (apply from the next batch)

### Arrangement experiments: small surface area
- The default batch is a handful of alternatives, 3 to 5, not ten.
- Each version contains only the instruments needed to hear the change, and only the section that
  contains the change. Fewer layers, less time.
- A version that needs the whole 40-48 s arrangement to make its point is the exception and says why.

### Voice-over and track descriptions: naturalness and simplicity rules
The announcements ("Batch 4 point 2, track 3. ...") are not good. Add rules to how titles, notes
and spoken text are authored. Starting set, to be agreed with Anthony:
- Say it the way a person would say it. No "point", no file-style ids, no stacked clauses.
- One idea per sentence, short sentences, plain words (reuse `tools/plainlint.py` and its vocabulary).
- Say what to listen for, not how it was made. No beat arithmetic in the announcement.
- Fixed and short: the spoken part names the version and the one change. Detail stays in the page notes.
- Voice test: read it aloud; if you would not say it to a person in the room, rewrite it.

## Decisions on batch 4.2 itself
- **Final arrangement starts with the scooped kick.**
- **Too many splashes.** Spread them out by a factor of 2 or 4.
- **Hat progressions:** none is quite right. Versions 7 and 9 are better.
  (In 4.2 the hat-focused tracks are 8 and 10. Batch 4.4 assumes batch 4's 7 and 9 and labels
  them "old no. 7" and "old no. 9"; not yet confirmed.)
- **Rule for hat layers:** layers that are individually quieter cannot be added as independent new
  layers to raise energy. It makes the section feel lethargic. A new layer has to add energy on its own.

## Mixing (deferred, not part of the arrangement batches)
- The kick needs more distortion.
- "Colour and space" is missing. May be a frequency-balance problem.
- Latent reference mismatches. Not yet characterised.

## Carried over, unresolved
- Track 3 (16th chops): one chop measured about 60 ms early; published with a note.
- Older batch scripts (`batch42.py`, `build_batch42.py`, `entries.py`) hard-code a scratchpad that
  no longer exists. The 4.3/4.4 scripts use `~/_agent_scratch` and a site checkout instead.
- **Hat layer B (perc 1, accented 16th closed hat) is quiet in practice:** adding it alone raises
  the highs only 0.9-1.6 dB (its chain sits at -12.6 dB). By the hat-layer rule above it may still
  feel lethargic where 4.4 adds it alone (tracks 1-4). Next: drop B, raise it, or add it
  only together with a loud layer. Layer E (quiet ride) is left out of 4.4 tracks 3-5.
- `verify4.py` names its MP3s with a fixed `2026-10-01-` prefix. The publish script sets the real
  date in the R2 key, so only the local file name is affected.
