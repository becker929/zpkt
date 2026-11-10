# HW002 batches 4.3 and 4.4: decisions (6 October 2026)

From Anthony's review of batches 4.3 and 4.4 on /skrng.

## The canonical shape

Batch 4.3 track 1, "Splashes every eight bars", was the best of both batches.
It is the canonical shape of the hat progression from now on.

| | Spec |
|---|---|
| Source bars | 121–122 twice (the scooped kick, 4 bars), then 125–140 (16 bars). 20 bars, 30 s. |
| Hat layers | A on bars 1–4, AB on 5–8, ABC on 9–12, ABCD on 13–20 (layers in `hats.py`). |
| Splash | Long (8 beats) when the kick comes in at bar 5, short (3 beats) at bar 13. |
| Instruments | Kick, rumble, splash, perc 1, perc 2 (`keep` 2, 3, 5, 6, 7). |
| Plan and set | `plan43.json` id `b43-01-splash-every-8-bars-30s`; set `HW002_121_v_b43-01-splash-every-8-bars-30s.als` in `~/_agent_scratch/HW002`. |

## What follows from it

- Batch 5 (mix alternates) is built on stems of this shape, not on the full-song arrangement.
- The 4.4 hat experiments are settled in favour of these four-bar steps.
- Still open from 4.2: hat layer B adds only about 1-1.5 dB of highs when it enters alone.
