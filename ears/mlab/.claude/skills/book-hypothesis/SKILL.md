---
name: book-hypothesis
description: Turn a claim from Anthony's mastering book (dither, EQ, compression, premaster, loudness, monitoring) into a runnable hypothesis YAML, run it on HW002 audio, and log the verdict. Use when Anthony brings a production hypothesis or asks "is it true that…".
---

# From a book claim to a verdict

Lab root: `~/Music/hw002-mastering-lab`. Template: `hypotheses/TEMPLATE.yaml`.

## Steps

1. **Restate the claim** as something measurable. One sentence. Name the chapter.
   Bad: "slow attack sounds punchier". Good: "at matched loudness, 30 ms attack keeps
   ≥0.5 dB more hit contrast than 1 ms on the HW002 kick section".
2. **Choose the metric** from the dotted keys in the template (e.g. `dynamics.transient_contrast_median_db`,
   `loudness.plr`, `tonal.group.low_mid`, `word_length.quietest_blocks_dbfs`). If no metric fits,
   say so and build one, with a calibration check, before running.
3. **Build variants.** One change per variant. Python ops for gain/EQ/dither/codec/platform;
   Live renders (`file:`) for Live devices and plugins. Always add `normalize_lufs` to processed
   variants unless loudness is the thing under test.
4. **Write predictions with thresholds before running.** Use `abs<` for "no change" claims.
5. **Add `listening.abx`** when the claim is about audibility or preference.
6. Save as `hypotheses/H###-slug.yaml` (next free number) and run
   `python3 -m mlab hyp run hypotheses/H###-slug.yaml`.
7. **Read `hypotheses/results/H###-slug/report.md`.** Check the measurement table for surprises,
   not just the verdict. A surprise may be an instrument fault: rerun calibration.
8. **Log it**: a new L-### in `LEARNINGS.md` (what, evidence, what it changes) and a row in
   `STATUS.md`'s hypothesis table.

## Guardrails

- A NOT SUPPORTED verdict is a finding. Do not tune thresholds after the run to rescue it;
  write a new hypothesis instead.
- Say which source tier the claim rests on (standard > paper > reference > expert > industry).
- If the claim needs audio the lab lacks (references, WAV premaster, stems), write the YAML anyway,
  mark the missing input, and tell Anthony exactly what to export.
