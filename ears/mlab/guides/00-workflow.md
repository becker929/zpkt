# Workflow: from Ableton export to a decision

The loop is short on purpose. Export, check, measure, test, listen, log.

## The loop

1. **Export** a premaster from Live into `audio/inbox/`.
   Settings: see [ableton-live-12.md](ableton-live-12.md#export-settings).
2. **Check** it: `python3 -m mlab premaster audio/inbox/<file>.wav`.
   Fix every FAIL in Live before going further.
3. **Measure** it: `python3 -m mlab measure audio/inbox/<file>.wav`.
   The sheet lands in `reports/`.
4. **Test** a claim: copy `hypotheses/TEMPLATE.yaml`, fill it in, run
   `python3 -m mlab hyp run hypotheses/H###-slug.yaml`.
5. **Listen** blind when the claim is about hearing: the run writes an ABX kit.
   Score it with `python3 -m mlab abx-score <folder> ABBA…`.
6. **Log** the verdict in `LEARNINGS.md` and the table in `STATUS.md`.

## Which variants come from where

Python ops are fast and exact. Use them for gain, EQ shapes, dither, codecs and platform simulation.
Renders from Live are the truth for Live's devices and plugins.
Use them for Glue Compressor, Limiter, Roar, Decapitator and anything with character.
A hypothesis can mix both: `file:` variants next to `from:` + `chain:` variants.

## Rules that keep results honest

- Compare at matched loudness. The runner's ABX kits always are.
- Change one thing per variant.
- Write the prediction before the run. Put the threshold in the YAML.
- A NOT SUPPORTED verdict is a result. Log it.
- If an instrument surprises you, test the instrument first (`python3 -m mlab calibrate`).

## Time budget per hypothesis

Writing the YAML: 5 minutes. Running: 20 s to 2 min on the demo.
An ABX session of 12 trials: about 5 minutes.
Rendering variants in Live by hand: 2 minutes each.
