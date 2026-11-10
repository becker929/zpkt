# Bass line from a percussion loop

Learned from "Ableton Bass Tutorial - Fast House & Techno Bass Patterns" by Finish More Music
(https://www.youtube.com/watch?v=HztFoqevNMU, 2:27). This card is our summary and our measurements, in our
own words; watch the original for the tutor's explanation. The recipe is in
[bass-from-perc-loop.recipe.json](bass-from-perc-loop.recipe.json).

## What it is

The bass line's rhythm is borrowed from a percussion loop. You lay short bass notes under the loop's
strongest body hits, never under its hats or shakers. Then you nudge the notes until the pattern grooves,
without caring about key. Last, you take the loop out. What is left is a bass line whose rhythm came from
the loop but no longer sounds like it.

## Why it works

- **Groove you would not program.** A good percussion loop already holds syncopated accents that a
  hand-programmed bass seldom finds.
- **It answers the kick.** In this genre the kick takes every beat, so the loop's useful body hits fall
  between the beats. In the tutor's final line no note lands on a beat: the bass answers the kick instead of
  doubling it.
- **Body hits only.** They carry the groove. Bass under hats only adds clutter in the low end.
- **It sounds written.** With the loop removed, nothing gives away where the rhythm came from, so the line
  sounds composed. Tune the bass to the loop only if the loop stays in the track.
- **The low end stays clear.** Short, decaying notes (16ths, one 8th) leave room for the kick.

## Steps (Live 12 Suite, stock devices)

| # | Step | Values |
|---|---|---|
| 1 | Set up the loop | 123 BPM, 4/4, arrangement loop 1.1.1 for 2 bars, fixed 1/16 grid |
| 2 | Pick a loop of medium density, neither sparse nor busy | track "Perc Loop" at −10.5 dB, warped to the tempo |
| 3 | Solo it and find its main hits | listen for the loudest body hits (congas, rims, toms), not the hats; in the tutor's loop most fall between the beats |
| 4 | Make a short bass sound | Operator: oscillator A only, sine, coarse 1; attack 0 ms, decay 200 ms, sustain −inf dB, release 50 ms; glide off; Operator volume −12 dB; track "Bass Line" at −6 dB |
| 5 | Put bass notes under the main hits, none on a beat, and move them until it grooves | the tutor's result is below |
| 6 | Listen to bass and loop together | judge the rhythm only |
| 7 | Take the loop out | deactivate its clip (key 0) and release the solos |
| 8 | Add the drums | kick on every beat, clap on 2 and 4, closed hats on the off-beat 8ths, a vinyl-crackle layer; drums +1.4 dB, crackle −12 dB |
| 9 | Keep it as a seed | vary and extend it in the track |

The tutor's final line has seven short notes over 2 bars: mostly 16ths with one 8th, none on a beat,
on two pitches a fifth apart (about A and E, measured from the audio because the tutor never names them).
We transcribed the exact positions for study; they stay in our private run workspace, not in this public
repo. Watch the original to see them.

The fader values (−10.5 and −6 dB) are seen on screen. The Operator output and the drum level are not shown.
We fitted them to the tutorial's audio, leaving each about 3 dB off: kits differ, and our perc substitute
has far less sub than the tutor's loop.

## Stock substitutes

| Tutorial used | Stock substitute |
|---|---|
| A percussion loop from a course pack | Core Library "Agogo Atabaques 112 bpm", bars 1–2, warped to 123 BPM (Beats). Or the tutor's loop rebuilt as notes on Percussion Core Kit's Conga Low Slap pad (kept in the private run workspace) |
| Bass one-shots sliced from an earlier course example | Operator sine as in step 4; or Simpler with a Core Library bass one-shot |
| Kick, tops loop, vinyl sample | 909 Core Kit (kick 36, clap 39, closed hat 42); Vinyl Distortion's crackle rendered once to an audio clip, because the device crackles with no input |

## The method as rules (Version B)

The tutor places notes by ear. Our explicit stand-in, applied to the stock Agogo Atabaques loop:

1. **Measure.** Onset strength per 16th in a body band (40–1500 Hz) and a hats band (5–16 kHz), averaged
   over two passes, with a detector calibrated on synthetic clicks.
2. **Classify.** A position is a hat when its hats band leads; otherwise it is a body hit.
3. **Candidates.** Body hits at least 0.35 as strong as the loop's strongest, and none on a quarter-note
   beat.
4. **Pick.** The strongest candidates, up to seven, with at least two per bar.
5. **Pitch.** A (33) under darker hits, E (40) under brighter ones. The first E is an 8th.

That gave six notes: A at 1.2.3, E at 1.4.3 (an 8th), E at 2.1.4, A at 2.2.3, E at 2.3.4 and A at 2.4.3.
Three of them share positions with the tutor's line.

## What our renders measured (11 October 2026)

Each render plays 16 bars at 123 BPM after a 2-bar lead-in:

- bars 1–4: the loop alone;
- bars 5–8: the loop and the bass;
- bars 9–16: the bass and the drums, with the loop's clips deactivated.

| Check | A, faithful | B, method on a stock loop |
|---|---|---|
| Bass notes within 15 ms of plan | 42/42, max 3.7 ms | 36/36, max 3.7 ms |
| Loudness by section, LUFS (raw) | −34.2 / −31.4 / −21.4 | −34.2 / −31.4 / −21.4 |
| Loop gone in bars 9–16 (template gain) | −0.03 to −0.05 | 0.00 to 0.03 |
| MP3 loudness, true peak | −14.4 LUFS, −1.2 dBTP | −13.7 LUFS, −1.1 dBTP |

An independent verifier passed both renders on shape, timing, pitch and delivery. Version B's first plan
read its detector 21 ms early, which put two notes on the wrong hits. The rule that every detector is
calibrated on synthetic clicks before it decides anything comes from that miss.

Anthony's verdict (12 October 2026): "Those sound really good."

## Notes for next time

- With sustain at −inf and a 200 ms decay, the 8th note sounds the same as a 16th. Raise sustain if note
  length should matter.
- Listen to B's note at 2.1.4. It sits on a mixed hit (a soft drum plus a shaker), right on the line
  between a body hit and a hat.
- The method needs a loop with off-beat body hits. Run 1's first stock pick had none, so screen loops with
  the same measure before building.
