# knobmap_hw002_kickgroup_v1 — ten knobs on the kick group bus, as the set is

Job: mailbox comments 5644205375 and 5644604509, queue item 3. One parameter
at a time, whole range, 13 steps, on the rig, tap the group bus, restore.

## What the bus is

`kick group` on HW002_14: members `kick` (track 2) and `rumble` (track 3),
rumble's LFOTool on. Chain on the bus: EQ Eight, Roar, Dist COLDFIRE, EQ
Eight, Compressor. Every step loop-recorded beats 0 to 32 of the real
arrangement (8 bars, 160 BPM, 12 s), tapped from the bus output into the
capture track. **Every row here is about kick plus rumble as heard through
the bus, not about a solo kick.** Each sidecar says so and lists the
members, their mute state, and every bus device's on-state.

Rig: 130 steps, zero dead bounces, zero write/read mismatches, every
parameter restored and verified, loop and capture track restored. Measurer
of record: the ears shim, crest and five band shares per step, as the SNTS
rows. Ten CSVs, one per row.

## The two things the map says about this set

**1. Roar is bypassed.** Its Device On reads 0.0, although every stage,
shaper and filter inside it is switched on. The five Roar rows (Drive, Tone
Amt, Blend, Shaper 1 Amt, Shaper 1 Bias) therefore swept a device that was
not in the signal path. Crest span 0.08 to 0.14 dB, sub share span 0.002.
**Null by construction**, kept because the sidecars prove it and because a
future reader needs to know Roar is off in this set.

**2. The compressor is idle at Anthony's setting.** Threshold -5.47 dB
(0.713 normalised), RMS model, 3:1, attack 0.08 ms, release 2.9 ms, makeup
off. The bus RMS is -9.3 dB, below the threshold. In the threshold row the
peak, RMS and crest are all frozen from 0.667 upward, which brackets 0.713:

| threshold | peak | rms | crest |
|---:|---:|---:|---:|
| 0.583 | -4.0 | -10.7 | 6.71 |
| 0.667 | -2.0 | -9.5 | 7.48 |
| 0.750 and up | -1.9 | -9.3 | 7.45 |

So Attack, Release and Ratio have nothing to act on and read flat by
physics (crest span under 0.1 dB). Knee, whose soft edge reaches 18 dB below
threshold, moves crest by 0.48 dB. **Threshold is the one live knob on this
bus.** Full row in `threshold_row.md`: 11 dB of crest span, from 17.8 at the
floor to 7.4 above 0.667. It is not monotonic in crest: under heavy
compression the 2.9 ms release lets the transient through and squashes the
body, so crest rises as threshold falls. Peak and RMS are monotonic.

## Skipped and deferred

- **Dist COLDFIRE**: skipped on the rig as agreed. The LOM exposes only its
  on/off. An offline row in isolation is a separate pack.
- **Per-hit measures** (decay40_ms, sustain_share): the pass ran and cost
  24 s a row, but `analysis.run hits` treats a file as one hit, so on a 12 s
  loop it returns the file: decay 13.7 to 14.0 s, sustain 0.997, every row.
  Not shipped. A per-hit pass on loops needs onset segmentation first; the
  runner's stem path has it. Second pass.

## What fought us

Nothing on the rig. The one thing that would have misled a reader is above:
two of the three devices the spec named are not active at Anthony's
settings, and the sidecar on-states are what caught it. Check `Device On`
and the operating point before planning a row.

## Suggested next

1. A "what Roar would do" pack: same five rows with Roar's Device On set to
   1 for the run and restored after. A different question from this one.
2. Attack, Release and Ratio at an operating point where the compressor
   works: fix Threshold at 0.4 for those rows, note it, restore.
3. COLDFIRE offline in isolation, DawDreamer, VST2 build.

No audio in this pack. No audio left the machine.
