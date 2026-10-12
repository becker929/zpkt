# Stock substitutes

Tutorials often use third-party samples and plugins. The practice uses Live 12 Suite's stock devices and
Core Library only, so every result can be rebuilt on the rig. For each third-party item, the recipe gives:

1. the closest stock substitute;
2. a **deterministic fallback**: a MIDI pattern (measured from the tutorial's audio) on a stock Drum Rack pad
   or instrument, so the rhythm can be reproduced without the sample.

A name is marked *used* if a run loaded it successfully, *rejected* if a run measured it and turned it down,
or *suggested* if it has not been tried yet. Confirm a suggested name in the browser before relying on it.

## By role

| Role | Stock substitute | Fallback / notes |
|---|---|---|
| Percussion loop | Core Library `Samples/Loops/Drums/Percussion/`: *used*: "Agogo Atabaques 112 bpm" (bars 1–2, warped to 123 in Beats mode, +1.9 dB clip gain; 7 off-beat main hits, medium density). *Rejected*: "Akeem Groove 120 bpm" (main hits only on the beat, too sparse), "Djembe 120 bpm" (17 off-beat hits, too busy) | The transient map as Drum Rack notes: *used* "Percussion Core Kit", pad "Conga Low Slap" (MIDI 38). A multisampled pad does not repeat sample for sample |
| Screening loops | run the method's own measure (`onsets.py --grid`, body and hats bands) on Live's warped render of each candidate before building | a loop is only a good fit if it has what the method needs (here: off-beat main hits) |
| Bass one-shot or sliced bass | *used*: Operator, oscillator A sine only, coarse 1, A 0 ms, D 200 ms, S −inf dB, R 50 ms, glide off; output −12 dB. *Suggested*: Simpler (one-shot) with a Core Library bass sample, or Drift for a rounder tone | with sustain at −inf, a 1/8 note sounds the same as a 1/16; raise sustain if note length matters |
| Kick | *used*: "909 Core Kit", kick on MIDI 36 | pattern from the tutorial's low-band onsets |
| Clap / snare | *used*: "909 Core Kit", clap on MIDI 39 (snare on 38) | label the backbeat by band: run 1's scrape missed it |
| Hats / shakers / tops loop | *used*: "909 Core Kit", closed hat on MIDI 42 (velocity 90) | high-band onsets give the pattern |
| Vinyl crackle / noise layer | *used*: Vinyl Distortion (crackle density 10, volume 0.5), **rendered once to an audio clip** on its own track | it crackles with no input, through the lead-in too (`recovery.md#device-self-noise`) |
| Pads, chords, leads | *suggested*: Wavetable, Drift, Meld, Analog, Electric, or Simpler with a Core Library sample | note the chord voicing from the piano roll or the audio |
| Saturation / distortion | *suggested*: Saturator, Roar, Overdrive, Pedal, Drum Buss, Dynamic Tube | a plugin's character never maps exactly; match the measured band balance |
| Compression / glue | *suggested*: Glue Compressor, Compressor, Multiband Dynamics | for the publish chain, Glue Compressor on Main instead of offline limiting |
| EQ / filter | *suggested*: EQ Eight, Channel EQ, Auto Filter | values in the device's own units; bisect with `str_for_value` |
| Space | *suggested*: Hybrid Reverb, Reverb, Echo, Delay | |
| Sidechain | *suggested*: Compressor with its sidechain from the kick track, or Utility gain automation | arrangement automation is not writable over the LOM; render or write it into the .als |

## Values

- Set dB and ms targets by bisecting the parameter's `str_for_value`. Live's display truncates (−10.45
  shows as −10.5), so aim at the lower edge, then read the value back.
- Clip gain has no `str_for_value`: probe it and measure the result.
- Unseen levels (synth output, drum bus) come from `balance.py` against the tutorial's audio. Say which
  cells you fit, because kits differ and no setting matches every one.
