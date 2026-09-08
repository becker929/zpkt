# First experiments once Live can be driven

Written for the consolidated Ableton skill (OSC + LOM + hands). Each item is
a hands ProjectConfig plus a measure from this repo. Ordered by what each one
unlocks for the register, not by difficulty.

## E1. Does the separator see a split duck?  (calibrates H34)
Build one 8-bar loop: kick, one sustained bass, sidechain from kick.
Render A: full-band duck. Render B: split duck (sub only, low band untouched),
matched so the sub dips the same depth as A. Bounce both, separate both with
Demucs, run `corpus2/band_pump.py` on the stems.
Read: sub-minus-low difference on the separated stem. If B shows the split
(>= 3 dB) the corpus verdict stands and the genre does not use it. If B does
not, the H34 verdict is a separator limit, and the register says so.

## E2. Pump depth in, pump depth out  (calibrates the whole pump column)
Same loop, sidechain depth swept 0, 3, 6, 9, 12, 15 dB in the plugin.
Bounce, separate, measure `bass_pump` and mix-level pump.
Read: slope of measured against set. Anything below 0.8 or above 1.2 is a
correction factor every pump number in parts two to four needs.

## E3. Kick body under the rumble  (calibrates kicks_by_position)
Kick alone, then kick with a rumble layer at -6, -12, -18 dB under it.
Read: decay40, centroid, sub share of the kick body with and without the
rumble present. This is the cleanest test of whether the position-based
kick finder measures the kick or the kick plus what sits under it.

## E4. Candidates through your own chain  (the note-five scene, minimal)
Take one of Anthony's demos as a project. Three configs that move one knob
each: body saturation, rumble duck depth, kick tail length. Bounce all three,
run the bench sheet, show the map. No preference model yet; just prove the
config-diff-to-sheet path works end to end.

## E5. Overnight kick breeding  (only after E3)
Generate kick chains from the device map, bounce, score with the meter and
the reference distances from the bench sheet. Keep the top decile, mutate.
The score is not "good"; it is "close to the references on measures the
listening test has validated". Stop when the listening test has under 50
answers, because then there is nothing to validate against.

## Plumbing
- Bounces land in the Drive folder under `tracks/` with the config hash in
  the file name; `lab/runner.py --local` picks them up unchanged.
- The vibe server's answers should post to the site's listening-test store
  rather than a second file, so the preference model has one history.
- Crash-avoidance rules should be runnable tests before E5, not before E1.
