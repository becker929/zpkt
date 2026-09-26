# Subject 3 — Compression & dynamics (Ch. 5–7)

Keywords: compressor, limiter, attack/release, knee, gain reduction, punch, macro- vs microdynamics.

## The idea in six sentences

A compressor turns level down by a ratio once it passes a threshold.
Attack sets how fast it reacts; release sets how fast it lets go.
The knee sets how gently it starts.
Slow attack lets a hit's front edge through, which reads as punch.
Macrodynamics are section-to-section changes; microdynamics live inside a beat.
A limiter is the extreme case: it holds peaks under a ceiling.

## Instruments

| Command / key | Answers | Calibration |
|---|---|---|
| `mlab probe` → render → `mlab comp-probe DRY WET` | threshold, ratio, knee, attack, release, makeup of any compressor | recovers three known settings: threshold ±0.1 dB, ratio within 5 %, attack within 1 ms |
| `dynamics.crest_db` | peak minus RMS for the file | sine 3.01, square 0.00 dB |
| `loudness.plr`, `loudness.psr_min` | how limited the file is, overall and in the densest 3 s | cross-checked TP and LUFS |
| `dynamics.block_crest_median_db` | typical peak-to-RMS inside 400 ms blocks (microdynamics) | analytic basis |
| `dynamics.transient_contrast_median_db` | punch: hit peak (0–10 ms) minus body RMS (20–120 ms) on main hits | synthetic kick loop: slow attack +, fast attack −, limiting − (L-006) |
| `loudness.lra`, `dynamics.short_term_p95_minus_p10` | macrodynamics | EBU 3342 cases within 0.01 LU |
| `dsp.compressor`, `dsp.limiter`, `dsp.master_to` | reference processors for Python variants | limiter holds its true-peak ceiling within 0.05 dB |

The probe signal: 20 s level ramp from -60 to 0 dBFS, then three 30 dB up/down steps.
Render it through a device with makeup at 0 dB. Attack and release are times to 63 % of the gain change.
Release reads about 5 ms long on devices with a peak hold (as ours has).

## HW002 baseline

PLR 13.4 dB, crest 14.8 dB, block crest 8.6 dB, hit contrast 8.1 dB, LRA 2.1 LU.
The loudest peaks are in the breakdown at 33–34.5 s, not on the kicks (L-010).
So the master limiter mostly works on one event. Limiting to -9 LUFS left per-hit punch unchanged.

## Experiments ready to run

- **H001** (done): -9 LUFS costs 5.4 dB PLR and gains nothing on YouTube. Punch unchanged (partly refuted).
- **H005** (done): Python compressor, attack 0.1 / 3 / 30 ms. Differences were small (L-015).
- *Map Glue Compressor*: render the probe at attack 0.3, 3, 30 ms and release 0.1, 0.4, 1.2 s, ratio 4. Nine files. Run `comp-probe` on each. Now you know what the labels mean.
- *Tame the breakdown event*: clip or lower 33–34.5 s by 3 dB in Live, then re-run H001. Expect PLR to fall less for the same loudness.
- *Kick punch per attack*: render the kick group through Glue at three attacks; compare `transient_contrast` at matched loudness.

## In Ableton Live 12

- Glue Compressor: bus-style, stepped attack and release, ratio 2/4/10, soft-clip switch. Good for gentle bus glue.
- Compressor: peak, RMS or expand detection; knee; lookahead. Better for precise, measurable settings.
- Limiter (12.1 and later): Standard, Soft Clip and True Peak modes, Maximize, lookahead, stereo link or M/S. Use True Peak mode for delivery (L-013).
- Anthony's chain has Decapitator, StandardCLIP, Roar and Dist COLDFIRE. Clippers change punch differently from compressors (see site note 7: the StandardCLIP map).

## Sources

- Primary: Giannoulis, Massberg & Reiss, "Digital Dynamic Range Compressor Design — A Tutorial and Analysis", *JAES* 60(6), 2012 (tier 2). The soft-knee formula in `dsp.gain_computer` comes from here.
- Primary: EBU Tech 3342, *Loudness Range* (tier 1).
- Secondary: Wikipedia, "Dynamic range compression" (tier 3).
- Expert: site note 7, "Measuring plugin controls on a real kick drum" (tier 4, this project).
