# Anthony's LFOTool on HW002_14 track 3 (rumble), read from the project file

| parameter | value | meaning |
|---|---|---|
| `bpmsync` | 1 | synced to host tempo |
| `rate` | 0.435 | one cycle per beat at 4/4 |
| `lfo_depth` | 1 | full depth |
| `vol` | 1 | volume modulation amount, full |
| `cut` | 0.5 | cutoff modulation amount: none |
| `res` | 0.5 | resonance modulation amount: none |
| `f_on_off` | 0 | filter section off |
| `xov_on` | 0 | crossover off, so the curve applies to the whole band |
| `smooth` | 0 | no smoothing |
| `phase` | 0 | no phase offset |
| `swing` | 0.5 | no swing |

Curve points (x, y as gain 0..1): [(0.0, 0.358), (0.5, 0.854), (1.0, 1.0)] then flat at 1.0.

Curve floor 0.358 of full gain = -8.9 dB at the start of each beat, back to 0 dB by the end.
