# First experiments once Live can be driven

## Status, 2026-09-09: Live CAN be driven

The rig exists and has produced real rows. Both control paths to Live work
(OSC for top-level params, LOM over MCP for arbitrary code). One of Anthony's
own sets, `SNTS Style track`, was opened as a copy-on-write clone, never saved,
and a knob on its Kick (G) was swept, bounced as an isolated stem per setting,
and measured. Two rows of the knob -> measure map are done:

- **Decapitator / Drive** (Style 0.5, AutoGain off), 0..1 then 0.4..0.7 fine.
  crest is NON-monotonic: ~9.8 dB at 0.0, local max ~11.1 dB near 0.6-0.625,
  8.1 dB at 1.0. sub_share is a smooth U with its minimum 0.558 at Drive 0.6.
  The crest peak (0.625) and sub trough (0.6) separate only at 0.025 steps;
  their apparent co-location at 0.6 was a resolution artifact. The energy
  leaving sub moves UP into low (0.245 -> 0.329) and mid, it is not lost.
- **StandardCLIP / Clipping threshold** (threshold_dB = 144*value - 120), same
  kick, 0.6..0.9. crest is a clean monotonic S-curve: floor ~4.3 dB, steep rise,
  ceiling ~8.7 dB (native). sub_share is near-flat (0.716..0.783), so the knob
  is nearly orthogonal. It inverts: target crest -> value is tabulated in the
  map. Clip harmonics land in mid/high/air, not sub.

Measures came from a provisional `measure_local.py` whose band-share maths is
copied verbatim from canonical `ears/loudness.py`, so shares are
corpus-comparable now. LUFS and true peak are NOT valid on these taps: the
stems are gain-scaled, and only ratios (band shares, crest) survive that.

What this changes below: E1-E3 are unblocked (they need exactly this rig).
E4 needs one of Anthony's demo projects named. E5 still waits on listening-test
answers. Two lessons from the first rows apply to every experiment here: sweep
the WHOLE range because real knobs are not monotonic, and pick a range that
CROSSES the band edge you measure or the share saturates flat.


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
