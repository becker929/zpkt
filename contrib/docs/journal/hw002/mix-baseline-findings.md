# HW002 Mix Notes: Baseline Findings & Next Steps

Recorded 18 November 2026.
Arrangement: `HW002_121_pp_mix.als` (160 BPM, 60.0 s arrangement, 25 tracks: 6 buses, 19 channel stems, 214 clips).
Baseline render: `hw002-mix-baseline.wav`.
Primary reference: `BSLS - I Peed On You But You Were Never Mine` (`matched/BSLS - full - -14LUFS.wav`, 160 BPM).

---

## 1. Measured Findings vs BSLS Reference

| Metric | HW002 Baseline | BSLS Reference (-14 LUFS) | Gap / Diagnostic |
|---|---|---|---|
| **Integrated Loudness** | -16.83 LUFS | -14.04 LUFS | Unmastered / uncalibrated raw bus gains |
| **True Peak Level** | -4.25 dBFS | -9.81 dBFS | Hot raw transient peaks eating dynamic headroom |
| **Crest Factor (Peak - RMS)** | **14.17 dB** | **5.79 dB** | **+8.38 dB gap**: transients punch through without body density |
| **Low-End Mono (<120 Hz)** | Side is -10.58 dB under mid | Side is -18.15 dB under mid | **Stereo phase cancellation**: low end lacks mono cohesion |
| **Deep Sub (25-45 Hz)** | 63.0 dB relative | 72.5 dB relative | **-9.5 dB sub deficit**: kick high-pass cut too aggressive |
| **Midrange (1-3.2 kHz)** | 42.0 dB relative | 53.4 dB relative | **-11.4 dB scoop**: lack of kick knock and bus distortion body |
| **Air (10 kHz)** | 32.3 dB relative | 39.1 dB relative | Sits balanced, but needs shelf control as density climbs |

---

## 2. Key Diagnostic Takeaways

1. **Crest Factor & Pre-Limiter Saturation:**
   - BSLS gets its low 5.8 dB crest factor through pre-limiter bus saturation, clipping, and dense drum grouping rather than master limiting.
   - HW002's raw stems currently peak at -4.25 dBFS with an RMS of -18.42 dBFS. A soft clipper or saturator (e.g., Ableton Saturator in Soft Sine or Curve mode) on the Kick bus is needed to round off the instantaneous 2-5 ms beater spike, lowering crest factor by 3-4 dB without softening the perceived transient punch.

2. **Mono Low-End Cleanliness:**
   - Below 120 Hz, side-band energy is currently only -10.6 dB below mid, causing low-end phase smear.
   - Must collapse frequencies <120 Hz to mono across the entire mix (via Utility / Eq8 side-cut).

3. **Sub & Midrange Restoration:**
   - Kick low-cut needs to be relaxed to bring back the 25-45 Hz sub weight (-9.5 dB gap).
   - Midrange presence (1-3.2 kHz) requires distortion drive (COLDFIRE / Saturator / Decapitator) on kick knock and synth stabs to fill the 11.4 dB spectral hole.

---

## 3. Step-by-Step Mixing Next Steps

1. **Kick Bus Staging & Crest Factor Control:**
   - Insert `Saturator` on `Kick bus`: drive into soft-clipping to tame the transient peak and elevate the sustained body.
   - Insert `Eq8` on `Kick bus`: relax high-pass filter down to ~28 Hz; add gentle mid bump around 1.6 kHz.

2. **Low-End Mono Summing:**
   - Insert `Utility` on `Main` (and sub buses) with `Bass Mono` enabled below 120 Hz. Ensure side energy drops <= -20 dB below mid.

3. **Sub-Bus Balance & Drum Bus Saturation:**
   - Balance the 6 summing buses (`Kick bus`, `Hats bus`, `Perc bus`, `Chord and splash bus`, `Break bus`, `Transitions bus`).
   - Add parallel saturation and light bus compression on `Hats bus` and `Break bus` to thicken mid-range textures.

4. **Main Bus Bus Glue & Master Limiting:**
   - Insert `Glue Compressor` on `Main` (30 ms attack, fast/auto release, 2:1 ratio, 1-2 dB gain reduction).
   - Calibrate master headroom (Main Utility at -6.0 dB) and compare level-matched A/B against BSLS.
