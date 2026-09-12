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


---

## 2026-09-12: stems sized from the whole set, and takes that do not line up

Both found by the Mac agent while running the LFOTool bypass job.

**Trailing silence.** `bounce_multitrack.py` sized every stem from
`song.last_event_time`, the last event anywhere in the set, rather than from
the source track's own clips. On HW002 that is 1630 beats against a track that
ends at beat 704: 614 s files, 264 s of music, 57% silence. Every stem in
`live_multitrack_bounce_v1` has this. Any window cut by fraction of file
length past 43% measured nothing. Fix: size from the track's `arrangement_clips`;
and in the lab, `duck_calibration.py` now finds the content end itself and
reports `trailing_silence_share`.

**Take alignment.** Two separate real-time recordings started 251 samples
apart (5.7 ms). Dividing them unaligned gave depths that wandered between
windows and a spurious split. An unconstrained cross-correlation made it worse
by returning a lag of exactly one beat, which is the material's periodicity,
not the offset. Fix: align by cross-correlation with the lag search
constrained to under half a beat. After alignment the four windows agree to
within 0.5 dB on the Mac, and a synthetic pair shifted by 251 samples comes
back with the lag found and a split of 0.1 dB.

**Pump saturation, confirmed on a second machine.** `duck_calibrate.json`
from the Mac, on the real HW002 kick: a true 24 dB duck reads 11.8, a true
40 dB reads 13.4. Same ceiling as measured here. The correction stands: every
published pump depth above about 12 dB is a floor.


---

## 2026-09-12, later: the bypass division over-read a 9 dB duck as "silence"

Three defects stacked in `duck_calibration.py bypass`, all found once the
device's true setting (a 9 dB pump) was known from `offline_plugins_v1`:

1. It divided two `grid.envelopes` outputs. That is an envelope FOLLOWER
   with release dynamics, right for finding beats in a mix, wrong for a
   ratio: on a decaying tail the release, not the signal, sets the slope.
   Now: zero-phase band-pass, square, average in 4 ms frames. No dynamics.
2. It measured depth against the curve's own maximum. A rumble decays away
   before the shaper's ramp reaches unity, so the curve's max sat near -3 dB
   and a 9 dB duck read as 6. The ratio is ducked over bypassed, so 0 dB is
   unity by construction; depth is now measured against 0.
3. The fold's last frames caught the NEXT onset wrapping in, and the sub
   band's filter pre-rings it earlier still. The dip is searched in the first
   90% of the beat, and the fold is anchored at the reference's own onset
   when the reference is impulsive (the kick grid's phase lands early).

Also: alignment now correlates envelopes inside a 25 ms window instead of
waveforms. Verified: a synthetic rumble-style pair with a true 9 dB duck at
onset reads 8.7 dB at 0 ms in both bands, split 0.03; a sustained pair with
a true 18 dB duck and a 251-sample offset reads 16 dB (frame smoothing) with
the offset found. The split is now taken from the onset gains, which is the
H34 question stated exactly: is the sub pulled down deeper than the low band
at the moment of the kick.


---

## 2026-09-12, later still: the duck measure calibrated at known depths on real material

DawDreamer hosting the VST2 LFOTool with a 160 BPM transport, Anthony's own
state loaded by name (69 of 70 parameters read back exactly), thirteen depth
steps on the trimmed un-ducked rumble, each render divided against that same
input. Known answer from the device's curve floor of 0.358: 8.9 dB at full
depth, 3.4 dB at half. Measured 8.1 (sub) and 9.4 (low) at full, 3.1 and 3.6
at half. **The duck measure tracks true depth within about 0.5 dB up to
9 dB on real material, and reports no split where there is none, within
1 dB.** That is requirement 2 done for this measure inside the range where
the genre actually sits (corpus median 7 dB). Above about 12 dB the corpus
estimator saturates and stays a floor; the division route does not, and is
the one to use when a bypassed render exists.

Two facts about the hosts: pedalboard cannot do this (no transport);
DawDreamer's `load_state` rejects the raw `.als` buffer, so state goes in by
parameter name from a pedalboard dump. Both must run from a foreground
shell.
