# First real multitracks: what they settled, and what they broke

Date: 2026-09-11. Source: `live_multitrack_bounce_v1`, produced by the Live
rig on Anthony's machine from the job spec in `live-multitrack-bounce.md`.

## What arrived

18 isolated per-track stems from two of Anthony's own sets, every one tapped
from its own Live track and never touched by a source separator.

| set | tracks | bounced | skipped |
|---|---:|---:|---|
| SNTS Style track 2026-04-21 | 44 | 6 | 4 groups, 33 muted or empty, 1 with a deleted instrument |
| HW002_14 | 18 | 12 | 4 groups, 1 muted, 1 empty |

The pair that matters is HW002 track 2 (`kick`) and track 3 (`rumble`),
siblings inside one kick group. A real kick and a real sub layer from one
arrangement, never blended and un-blended by Demucs. Both are 614 s at 44.1
kHz, 160 BPM.

The bounce was not uneventful and the run log is honest about it: a
Hammerspoon config interfered with Live and baked dropouts into several
takes, which were detected and re-bounced after a fix; the Mac slept once and
froze the transport, producing a false silent bounce; and one SNTS track was
confirmed silent at source because its instrument was deleted from the
project back in April.

## What the device chain settles on its own

The `rumble` track's chain, from its sidecar:

    Utility -> Shifter -> Decapitator -> EQ Eight -> LFOTool -> Utility

Only one of those is dynamic. LFOTool is a tempo-locked shaper, the same
family as Kickstart. EQ Eight here is static. So on this track the duck is
applied by a shaper, and a shaper of that kind applies one curve to the
signal, not a different curve per band.

That is most of an answer to H34 without measuring anything. The advice says
duck the sub deeper than the low band. You cannot do that with the device
that is doing the ducking here. For this producer, on this track, the split
duck is not declined on taste: it is not expressible in the tool.

One honest gap: the sidecar records device names, not parameter values.
LFOTool can also modulate a filter rather than a volume, which would not be
broadband. Which mode this instance uses is not visible in what was captured.
The next bounce should record the parameter values, not just the chain.

## What broke

The corpus measure does not survive being pointed at a solo stem.

Run on the real kick and rumble, `band_pump.py`'s measure reports a sub dip
of 40.6 dB and a low dip of 70.5 dB. The corpus median is about 7 dB. A
per-beat variant, written to avoid the silence problem, reports 111 dB and
151 dB. None of these are ducking depths. They are what happens when a
ducked solo stem approaches the noise floor between kicks and a logarithm is
taken of something near zero. On a full mix the gaps are filled by other
instruments and the estimator stays in range, which is why the corpus numbers
looked sane.

Two controls establish this rather than assuming it.

**Control 1: a known broadband duck.** Apply an exact, frequency-independent
gain duck of known depth to a clean two-tone bass and ask the measure what it
sees.

| true duck | measured sub | measured low | reported split |
|---:|---:|---:|---:|
| 6 dB | 4.48 | 4.43 | +0.05 |
| 12 dB | 8.06 | 7.90 | +0.16 |
| 24 dB | 12.25 | 11.91 | +0.34 |
| 40 dB | 13.92 | 13.49 | +0.43 |

Two things follow. The measure does not invent a split, which is reassuring
for the corpus verdict. But it saturates: a true 24 dB duck reads as 12 dB,
a true 40 dB reads as 14 dB. **Every pump depth in parts two to four is a
floor, not a measurement, once it passes about 12 dB.** That is a correction
factor the register needs, and it is the answer E2 was designed to find.

**Control 2: add more duck and see if the number moves.** Take the real
rumble and apply a further 12 dB, then 24 dB, of exact broadband duck on top
of whatever it already has. If the measure were reading the duck, the numbers
would climb.

| case | sub | low |
|---|---:|---:|
| rumble as bounced | 40.6 | 70.5 |
| rumble, plus 12 dB | 44.7 | 74.4 |
| rumble, plus 24 dB | 46.0 | 76.9 |

Doubling the ducking in dB terms moves the reading by about 5 dB. The number
is dominated by the silent stretches, not by the duck. It is not measuring
what its name says.

The per-beat variant fails its own control too: on a true broadband 6 dB duck
it reports a 1.7 dB split and on a 12 dB duck a 4.9 dB split, both spurious,
because the minimum of a band envelope inside a beat sits near a zero
crossing.

## Where H34 stands

Still open, but for a better reason than before, and with a sharper next step.

- The corpus verdict (median sub minus low of -0.2 dB across 532 separated
  bass stems) is not overturned. Control 1 shows the measure does not
  manufacture a split, so the corpus answer stands on its own terms.
- The real multitrack cannot yet confirm or deny it, because the estimator
  breaks on solo stems.
- The device chain argues the technique is absent here for a tooling reason
  rather than an aesthetic one.

## The decisive next run

Stop estimating the gain curve from the ducked signal. Recover it exactly.

Bounce the `rumble` track twice from the same arrangement: once as it is, and
once with LFOTool bypassed and nothing else changed. Divide the first by the
second, sample by sample, and the quotient IS the gain curve the shaper
applies, with no estimator in the way. Then ask whether that curve differs
between the sub band and the low band, which answers H34 for this track
exactly rather than statistically.

The same trick calibrates the corpus: apply that recovered curve at known
depths to full mixes and see what `band_pump.py` reports, which converts
every published pump number from a floor into a value.

---

## Postscript, 2026-09-12: the decisive run happened, and it answered

The Mac agent ran the double bounce (`results/live_rumble_bypass_v1/` on
the branch): the rumble as it is, and the rumble with only LFOTool bypassed,
from one clone in one sitting, tapped pre-group so the kick group's
Compressor, Roar and COLDFIRE could not contaminate the division.

**LFOTool applies one broadband duck, to near silence. There is no split.**

- Timing: the sub band bottoms out 344 ms into a 375 ms beat, the low band
  16 ms into it. Those are 31 ms apart across the beat boundary, not 328.
  One curve pulls both bands down at the same instant.
- Depth: reported 37 dB (sub) and 56 dB (low), and neither is a depth. The
  calibration run on the same kick shows the estimator saturating near 12 to
  13 dB, and an independent fold returned -120 dB in the 150 to 400 Hz band,
  which no shaper can do. These are noise floors. The duck goes to silence
  and the measure runs out of signal.
- LFOTool exposes only its on/off to the Live API and stores its state as an
  opaque blob, so its settings cannot be read by any route. The measurement
  answers the question the settings would have: it shapes volume, broadband.

So for this producer, on this track, H34's technique is absent because the
device that does the ducking cannot express it. The corpus verdict on 532
separated stems stands, and now has one exact real-instrument confirmation
behind it.

Two corrections to the numbers above, found on the Mac:

1. **The multitrack stems were 57% trailing silence.** The bounce sized each
   pass from `song.last_event_time` (1630 beats), but the tracks end at beat
   704. So 614 s files held 264 s of music, and any window past 43% measured
   silence. That is a plausible contributor to the 40 dB and 70 dB readings
   reported above; the 35% window used for the controls was inside the
   music, so the calibration conclusions hold. The bounce spec now sizes from
   the source track's own clips, and `duck_calibration.py` measures content
   length rather than file length.
2. **Two real-time takes are not sample-aligned.** They landed 251 samples
   apart, and unaligned division returned unstable nonsense. A naive
   cross-correlation locked onto one whole beat, the material's own period.
   The tool now aligns with the lag search constrained to under half a beat,
   verified on a synthetic pair shifted by 251 samples.
