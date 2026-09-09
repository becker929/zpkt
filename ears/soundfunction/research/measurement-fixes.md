# Measurement fixes

Defects found in the measurement stack, what they affected, and what changed.
Each entry states how the defect was caught, so the same trap can be checked
for elsewhere.

---

## 2026-09-09: decay and duration were measuring pitch, not time

**What was wrong.** `analysis/signal_features.describe_hit` computed both
`decay_ms` and `duration_s` by scanning the RAW absolute waveform for the
first sample that fell below a threshold after the peak. An oscillating
waveform passes near zero every half cycle, so the first sub-threshold sample
arrives within half a period of the peak no matter how long the sound actually
lasts. Both numbers therefore tracked the frequency of the sound, not its
length.

**How it was caught.** By checking listening-test stimuli against real
one-shots. The survey plays a hat with a 15 ms tail against the same hat with
a 250 ms tail and asks which is more of a hat. Measured, both came back as
`decay_ms` 0.113. A controlled sweep of five hats from 15 ms to 250 ms
produced 0.113, 0.295, 0.068, 0.068, 0.113: no ordering at all. Ground truth
from a smoothed envelope on the same files was 5.0 ms rising to 85.4 ms.

**What it affected.** `decay_ms` is one of the features
`analysis/classify.py` trains on (it is not in that file's DROP set), so the
full classifier carried one pure-noise feature. `duration_s` IS dropped
there, and appears in one lab report row. The corpus and stem work were NOT
affected: they use `decay20_ms`, `decay40_ms` and `sustain_share` from
`analysis/hits_extra.env_timings`, which windows the signal properly. The
browser role meter was not affected either: it uses the PORTABLE feature set,
which excludes `decay_ms`.

**The fix.** Both quantities now come from an amplitude envelope, never from
raw samples. The envelope is the magnitude of the analytic signal, which is
exact for a modulated sinusoid at any frequency, lightly smoothed with an
overlap-normalised moving average so the smoother does not attenuate the first
sample and drag the measured peak down with it.

Two traps were found while fixing it, both worth remembering:

- A short RMS window is itself frequency-dependent. A 2 ms window holds a
  tenth of a cycle at 50 Hz, so the envelope of a deep kick stays ragged and
  crosses the threshold early. Measured with 2 ms RMS, a 50 Hz and a 2 kHz
  tone with identical decay read 66 ms and 116 ms.
- The analytic envelope has a numerical floor near -50 dB, so a -60 dB
  threshold cannot be read off it directly: it returned 245 ms for a tone
  whose true -60 dB point is at 69 ms. `duration_s` is therefore fitted from
  the decay slope over the reliable region, peak down to -30 dB, and
  extrapolated to -60 dB. Same idea as the existing t60 estimate.

**Accuracy after the fix**, against exponential decays with known answers:
within 1% of the exact -20 dB time for decays of 20 ms and longer, +22% at
5 ms (the 2 ms reporting grid), and within 5% across 50 Hz to 10 kHz.

**Effect on the real one-shot library** (median `decay_ms`, 318 sounds):

| job | before | after |
|---|---:|---:|
| clap | 0.19 | 26 |
| hat_closed | 0.11 | 72 |
| hat_open | 0.09 | 245 |
| impact | 0.16 | 196 |
| kick | 1.79 | 102 |
| pad | 0.43 | 406 |
| perc | 0.41 | 76 |
| riser | 0.54 | 192 |
| rumble | 3.24 | 169 |
| stab | 0.43 | 266 |

Every job previously reported a decay under 4 ms, including pads.

**Regression tests.** `analysis/test_features.py` now asserts that decay rises
with decay time, that a 20x longer tail reads as clearly longer, that decay
does NOT move when only pitch changes, and the same for duration.

**What it cost, measured.** Almost nothing in the classifier, as it turns out.
Retraining on the synthetic library and testing on the real one, before and
after the fix, with identical feature schemas:

| | before | after |
|---|---:|---:|
| synth to real, chosen features | 0.346 | 0.346 |
| synth to real, forest on all features | 0.374 | 0.358 |
| union cross-validation | 0.748 | 0.748 |

The feature selector was already preferring the properly windowed
`decay40_ms` and `sustain_share` over the broken `decay_ms`, so the model
never leaned on it. The cost was to anyone READING the numbers: the library
tables and the lab's "duration to -60 dB" row reported a pad decaying in
0.43 ms. No published corpus figure moves, because none of them cite these
two fields.

**A trap worth recording.** The first before-and-after comparison showed
transfer accuracy falling from 0.346 to 0.299, which would have been a
striking and wrong finding. The cause was schema drift, not the fix:
`analysis.run hits` does not produce `decay20_ms`, `decay40_ms` or
`sustain_share`. Those come from a second pass, `analysis/hits_extra.py`,
and re-extracting a library without re-running it silently drops three
columns, including the two the selector likes best. Always re-run
`hits_extra.py` after `analysis.run hits`, and diff the column sets before
comparing two models.
