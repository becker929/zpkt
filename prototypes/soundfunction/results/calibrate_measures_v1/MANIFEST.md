# calibrate_measures_v1 — requirement 2, five measures against known answers

"Every measure on the sheet checked against a case where the answer is known,
and corrected where it bends." Cases built to the research agent's five
corrections (mailbox 5646120288). Each JSON records the measure's exact
definition, the case parameters, the truth computed on the same clean
samples with the stated formula, what came back, the error, and pass or fail
against the stated tolerance. Table in `summary.md`.

## Four hold. One does not.

**grid lock passes.** Tempo within 0.3% of true at every jitter, on clicks
and on 50 Hz bursts with a 300 ms decay, at 140, 150 and 160 BPM. Phase
holds within 1.5 ms up to 10 ms of jitter and drifts to 3 to 5 ms at 20 ms.
Worth noting the lock score is *higher* on bursts (1.000) than on clicks
(0.599): the measure prefers real kicks to the easy case.

**sustain share passes exactly**, to four decimal places, at all five
plateau fractions. Its definition is energy after the first 50 ms over total
energy, and the truth computed with that same formula on the constructed
samples matches to 0.0000. Note the built plateau fraction is *not* the
truth: a 0.1 plateau gives a 0.31 sustain share. Anyone reading the number
as "fraction of the hit held at level" will misread it.

**band shares pass off the edges**, within 0.001 of the built ratio down to
20 dB SNR, drifting to 0.75 at 10 dB and 0.47 at 0 dB. Tones placed *on* a
band edge are recorded, not judged, because there is no single true band for
them; those rows show how the three vocabularies split the same signal:

- `signal_features.BANDS`: sub 20-60, low 60-150 (six bands)
- knob-map notation: `sub_share` = 20-150, the library's sub + low
- the ears shim: a two-way split, 0.497 / 0.503 on the edge case

That is three meanings for one word, now documented with numbers.

**crest passes under clipping**, exactly, at all five ceilings. Its trap is
elsewhere and the padding rows quantify it: crest is peak over RMS across
the *whole buffer*, so trailing silence inflates it by +0.14 dB per half
second, +0.54 dB at two seconds. **Window rule: never compare crest between
buffers of different silence content.** That rule matters directly, because
the stems this project measures were 62% trailing silence until today.

## kick body fails, and the bias is frequency dependent

`decay40_ms` under-reads the analytic decay by 17 to 37% at every frequency
and decay constant tested. Twelve of twelve rows fail the 10% tolerance.

The three-column design separates two causes. An independent analytic-signal
envelope on the same samples already costs 1 to 25%, worse as the decay gets
faster, because a 40 Hz cycle is 25 ms and a fast decay is over before the
envelope resolves it. The library costs a further 15 to 35% on top of that
at the slower decays. At f0 40 Hz the total error is -30 to -37%; at 60 Hz
it is -17 to -25%. **A deeper kick reads as a shorter kick.**

Two rows are worse than a bias and should be treated as broken: f0 40 and 60
at decay 100, where the envelope reference returns 168.6 and 108.5 ms against
an analytic 46.1. At that decay the burst is nearly over within a few cycles
and the envelope estimate is meaningless, not merely biased.

**Consequence for published numbers.** Any comparison of kick body length
across sounds of different pitch is confounded. The corpus decay40 numbers
are not wrong by a constant; they are wrong by an amount that depends on the
sound's own frequency, in the same direction as the thing they are being used
to compare. This one needs a fix in the measure, not a caveat next to it.

## What fought us

The first version of this pack had three bugs of my own, all found by
running it: `fixtures.click_track` and `sine_burst` return tuples, not
arrays; `signal_features._band_shares` wants an STFT magnitude, not a
one-dimensional spectrum; and the first sustain-share truth used the built
plateau fraction rather than the energy ratio the measure actually computes,
which would have reported a real measure as broken. The control needs a
control.

No audio in this pack.
