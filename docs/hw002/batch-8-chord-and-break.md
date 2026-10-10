# HW002 batches 8.2-8.7: the chord loop and the break (9 October 2026)

Written by Claude Code from one session with Anthony. Batches are on /skrng (site PRs #59, #60).

## What we found

- **The chord loop was missing.** The processed synth chord loop (track "12-2022-06-02-001") plays under
  the intro, the peak and the outro. The canonical shape muted it, so batches 4.3-8.1 never had it.
- **It sits about 21 LU under the rest of the mix.** Its Utility is at -8.33 dB and 10 % width.
  Its core is 250 Hz-1 kHz, 6-12 dB under the rest. Above 2 kHz it is 26-46 dB under, behind the hats.
- **Colour alone cannot lift it.** A +12 dB shelf moves the mix's highs by 0.2 dB. Colour and width
  are only heard once the chord is up, so 8.3-8.5 sit on the chord at +8 dB.
- **The chord's COLDFIRE was bypassed inside the plugin.** Its preset "Shine Bright" (Tube into
  Transformer) had the plugin's own Bypass on. Live's Device On did nothing. Fixed in the kits.
- **COLDFIRE needs Configure before automation.** Live exposes no plugin parameters until they are
  configured. That takes the GUI: unfold the device, Configure, touch each knob. Done on 9 Oct for
  the chord (Drive A/B, Mix, Color) and the Break group (Drive A, Color, Mix), saved in kits c8x4,
  c8x16 and k8x16 only.
- **COLDFIRE on the chord costs 5.4 LU at any drive.** Its Colour is a tilt: 0 darkens, 1 brightens.
- **Width adds loudness.** 50/100/150 % add 0.9/2.7/4.6 LU, so 8.4 is loudness-matched.
- **Supermassive short and tight mostly costs level** (0.2-2.2 LU). Its texture is time-smear,
  which band levels do not show. Judge 8.5 by ear.
- **The break is nearly all Break group,** so each version's -14 LUFS matches it. In the song the
  break is about 3.5 LU louder than the drop (batch 4.2 already tested break level).

## The batches

| Batch | Baseline | Alternatives | Matched |
|---|---|---|---|
| 8.2 chord level | batch 6 "all" | chord +4 / +8 / +12 dB | no (it is about level) |
| 8.3 chord colour | chord +8 dB | COLDFIRE Colour 0.5 / 0.75 / 1 | within 0.2 LU |
| 8.4 chord width | chord +8 dB | width 50 / 100 / 150 % | within 0.2 LU |
| 8.5 chord texture | chord +8 dB | Supermassive short, Mix 0.3 / 0.55 / 0.8 | within 0.3 LU |
| 8.6 break space | the break | Hybrid Reverb 70 / 80 / 90 % wet (set 50) | by -14 LUFS |
| 8.7 break colour | the break | COLDFIRE Colour 0.3 / 0.5 / 1 (set 0.7) | by -14 LUFS |

## The pipeline

1. `hands/scripts/probe_pack/ab_live.py source_chord|source_break` writes a source set offline.
2. `hands kit template KIT SRC START END P` (run in `hands/`) builds a kit in Live.
3. `sweep8.py NAME` renders a sweep or a batch in views: mix, solo (the target), rest.
4. `ears/mlab/spikes/hw002_mixclimb/measure8.py NAME` reports LUFS, LU under the rest, bands, width.
5. `publish8.py NAME --upload` cuts the A/B tracks, uploads them and writes the site manifest.
6. Site PR, merge, check the deploy, then ntfy.

Open: Anthony's listening on 8.1-8.7. Then the next range follows the preferred end.
