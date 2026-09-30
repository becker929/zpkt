# knobmap_hw002_kickgroup_v2_thr040 — Attack, Release, Ratio at a working operating point

**Operating point 0.4, not Anthony's setting.** Every sidecar and CSV row
carries that label. Threshold was held at 0.4 normalised for all three rows
so the compressor was actually compressing (at his 0.713 it is idle, see
knobmap_hw002_kickgroup_v1), then restored to 0.7132 and read back.

Same bus, loop, tap, measurer and rig procedure as v1: kick group (kick +
rumble, LFOTool on), beats 0 to 32, 13 steps, restore each parameter after
its row. 39 steps, zero dead bounces, zero write/read mismatches.

| row | crest at min | crest at max | crest span dB | sub share span |
|---|---:|---:|---:|---:|
| Attack | 10.00 | 10.37 | 1.19 | 0.025 |
| Release | 9.95 | 9.56 | 1.67 | 0.024 |
| Ratio | 7.52 | 12.93 | 5.98 | 0.041 |

At the idle setting all three spanned under 0.1 dB. With the compressor
working, Ratio is the strong knob, 6 dB of crest, and it is a plausible
clean inverse for crest. Attack and Release each move crest by 1 to 2 dB.
Per-step values in the CSVs. No audio in this pack.
