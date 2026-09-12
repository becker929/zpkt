# knobmap_hw002_kickgroup_v3_roar_on — what Roar would do

**Roar's Device On forced to 1, not Anthony's setting.** In HW002_14 Roar is
bypassed (`Device On = 0.0`), which is why the v1 Roar rows were null. These
rows answer a different question: what would happen if the assistant proposed
turning Roar on. Device On was restored to 0.0 and read back at the end.

Same bus, loop, tap, measurer and procedure as v1 and v2. 39 steps, zero
dead bounces, zero write/read mismatches. Every sidecar carries the forced
state.

## Turning Roar on is itself the biggest move

With Roar bypassed the bus sub share sits at 0.901. With Roar on it drops to
about 0.77 at the swept midpoints. That is a larger change than any of the
three knobs makes, and it is the move a proposal would actually be making.

| row | crest min | crest max | crest span dB | sub share span |
|---|---:|---:|---:|---:|
| Drive | 6.12 | 8.45 | 2.33 | 0.052 |
| Tone Amt | 7.42 | 7.92 | 0.50 | 0.066 |
| Blend | 7.41 | 7.45 | 0.04 | 0.002 |

**Drive** is the usable knob: 2.3 dB of crest and 0.05 of sub share across
its range. **Tone Amt** moves the spectrum more than the dynamics, 0.066 of
sub share for 0.5 dB of crest, so it is a colour control here, not a punch
control. **Blend reads flat**, 0.04 dB and 0.002. On this device at these
settings Blend is not a dry/wet between processed and unprocessed bus; it did
not change the output measurably. Recorded as observed, not explained. Worth
one check against Roar's own documentation before any row is built on it.

No audio in this pack.
