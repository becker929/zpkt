# Subject 2 — EQ (Ch. 4)

Keywords: parametric vs shelving, surgical cuts, tonal balance, midrange, equal-loudness contour, psychoacoustics.

## The idea in six sentences

A parametric band lifts or cuts a region with a set centre and width (Q).
A shelf tilts everything above or below a corner frequency.
Surgical cuts are narrow and deep; tonal moves are broad and small.
Mastering EQ is mostly broad: half a decibel to two decibels, low Q.
The ear's sensitivity to bass and treble falls as playback gets quieter.
So a mix judged loud sounds thinner quiet, and phones make it worse.

## Instruments

| Command | Answers | Calibration |
|---|---|---|
| `mlab spectrum FILE` | 1/3-octave levels, seven band groups, slope in dB/octave, stereo per band | pink noise reads -3.0 dB/oct and flat within 1.5 dB |
| `mlab spectrum FILE --ref REF` | tonal difference vs a reference, both loudness-normalised | same |
| `mlab spectrum FILE --phon 60 --ref-phon 83` | per-band perceived change between two listening levels | ISO 226 identity at 1 kHz within 0.05 dB |
| `mlab probe` then `mlab eq-diff DRY WET` | the curve a Live EQ (or any device) actually applied | recovers a known peak + two shelves within 0.3 dB |
| `dsp.eq(x, sr, bands)` | Python EQ: peak, lowshelf, highshelf, highpass, lowpass (RBJ cookbook) | used as the known answer above |

Band groups: sub 20–60, bass 60–250, low-mid 250–500, mid 500–2k, upper-mid 2–4k, presence 4–8k, air 8–20k Hz.

## HW002 baseline (L-012)

| Group | dB re total |
|---|---|
| sub | -7.4 |
| bass | -2.7 |
| low-mid | -15.4 |
| mid | -8.8 |
| upper-mid | -15.2 |
| presence | -16.9 |
| air | -20.0 |

Slope -4.2 dB/oct: darker than pink noise. The 1/3-octave peaks sit at 63–80 Hz and 800 Hz.
Low-band correlation is 0.86: bass is mostly, not fully, mono.

## Experiments ready to run

- **H004** (done): low-mid hole and a +3 dB bell at 350 Hz. Supported; ABX kit waiting.
- *Measure EQ Eight*: put `audio/renders/probes/eq_probe_pink.wav` on a track, add EQ Eight with one move, export, run `eq-diff`. Repeat per filter type. This builds a map of what the knobs really do.
- *Loudness-level balance*: `--phon 60 --ref-phon 83` shows how much sub and air vanish at phone level. Use it to argue a small low shelf.
- *References*: put 3–5 genre references in `audio/refs/`, then `mlab refs audio/inbox/x.wav audio/refs`.

## In Ableton Live 12

- EQ Eight: eight bands; types include low/high cut (12 or 48 dB/oct), shelves, bell and notch. Stereo, L/R and M/S modes. Turn on oversampling ("Hi Quality") for high-frequency boosts.
- Use Spectrum after EQ Eight to watch the result, but decide by ear at matched level.
- For M/S work on the bass: EQ Eight in Side mode, low cut on the sides, or Utility's bass mono.

## Sources

- Primary: ISO 226:2023, *Acoustics — Normal equal-loudness-level contours* (tier 1). The code uses the 2003 table; the 2023 revision differs by about 1 dB at most for 20–90 phon.
- Primary: Suzuki & Takeshima, "Equal-loudness-level contours for pure tones", *JASA* 116(2), 2004 (tier 2).
- Primary (EQ maths): R. Bristow-Johnson, *Audio EQ Cookbook* (W3C Note, 2021) (tier 4).
- Secondary: Wikipedia, "Equal-loudness contour" (tier 3).
