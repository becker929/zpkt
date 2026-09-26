# Subject 1 — Dither & bit depth (Ch. 15)

Keywords: dither, bit depth, word length, truncation, export/DAW settings.

## The idea in five sentences

Every bit of word length buys about 6 dB of dynamic range.
Cutting bits without dither turns the rounding error into distortion that follows the music.
Dither adds a little random noise first, so the error becomes steady, harmless hiss.
TPDF dither is the default because its noise does not pump with the signal.
Dither once, at the last reduction, and never on a 32-bit float file.

## Instruments

| Command | Answers | Calibration |
|---|---|---|
| `mlab bitdepth FILE` | container, effective bits, DC, quiet-floor level, noise-shaping tilt, verdict | effective bits exact on 16/24-bit test files; floors match theory to 0.2 dB |
| `dsp.quantize(x, bits, dither, shaping)` | makes 16/24-bit versions with none/RPDF/TPDF, optional noise shaping | error floors: none -101.1, RPDF -98.1, TPDF -96.3 dBFS at 16 bits |
| `dsp.truncate(x, bits)` | true truncation (floor), for the bad case | harmonic share of error > 8 dB above TPDF on a fading tone |
| `bitdepth.truncation_distortion(orig, reduced, sr, f0)` | how much of the error lands on harmonics | analytic |

Reference floors at 16 bits (full scale ±1):

| Reduction | Error rms |
|---|---|
| Rounding, no dither | -101.1 dBFS |
| RPDF dither | -98.1 dBFS |
| TPDF dither | -96.3 dBFS |

## HW002 baseline

The demo never gets quieter than about -22 dBFS per 100 ms (L-014).
A 16-bit floor at -96 dBFS is 74 dB below that. Dither is not audible here.
It will matter in fades, reverb tails and the very end of the Short.

## Experiments ready to run

- **H002** (done): 16-bit TPDF vs truncation on the demo. Supported, with the MP3 caveat.
- *Fade test*: export the last 5 s with a long fade. Compare `quantize(tpdf)` vs `truncate` with the ABX kit boosted in Python (`gain` op, +40 dB). Expect truncation to sound gritty and pitched.
- *Noise shaping*: `quantize(shaping=true)` moves the floor up the spectrum. `mlab bitdepth` should report a tilt above +8 dB.

## In Ableton Live 12

- Export premasters as **32-bit float, no dither, Normalize off**. Nothing is lost.
- If a 16-bit file is ever needed (CD, some distributors), dither is chosen in the export dialog. Live offers no dither, triangular, rectangular and POW-r 1/2/3 (verify in the manual; the page could not be fetched this session).
- Dither exactly once. If a mastering plugin already dithers, set Live's to none.
- YouTube re-encodes to AAC/Opus anyway; its coding noise dwarfs any dither choice.

## Sources

- Primary: Vanderkooy & Lipshitz, "Dither in Digital Audio", *JAES* 35(12), 1987 (tier 2).
- Secondary: Lipshitz, Wannamaker & Vanderkooy, "Quantization and Dither: A Theoretical Survey", *JAES* 40(5), 1992 (tier 2).
- Reference: Wikipedia, "Dither" — audio section (tier 3).
