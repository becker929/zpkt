# Learnings

Newest last. Each entry: what we saw, the evidence, and what it changes.
IDs are permanent. Cite them from guides and hypotheses.

## Setup and tooling

**L-001 · 2026-09-25 · The Mac shell here is a Linux VM.**
The Cowork shell on the Mac mini runs Linux (aarch64), not macOS.
It sees only folders connected to the session, currently `~/Music`.
It cannot launch or drive Ableton Live.
`~/_tmsmsm` (where HW002's `.als` lives) could not be granted to this session.
Change: Live-driving work needs a native session on the Mac with the
`ableton-live-control` skill; this lab consumes its renders (guides/ableton-live-12.md).

**L-002 · 2026-09-25 · Drive files over 10 MB are out of reach.**
The Drive connector downloads files of 10 MB or less.
Neither shell can reach drive.google.com directly.
We got `HW002_1min-2026-08-13T2107.mp3` (3.4 MB). `HW002_9.mp3` (10.9 MB) and `HW002.zip` (230 MB) are unreachable.
Change: Anthony drops exports into `~/Music/hw002-mastering-lab/audio/inbox/` directly.

**L-003 · 2026-09-25 · `ears` loudness numbers are not calibrated.**
In `becker929/ears/src/ears/loudness.py`, `true_peak_db` is the linear sample maximum.
It is neither in dB nor a true peak.
Mono input is duplicated into two channels, which adds about 3 dB to LUFS.
Short-term and momentary values run the gated integrated meter on short blocks.
The research notes already warned that LUFS and true peak were not valid on those taps.
Change: use `mlab.loudness` (EBU 3341/3342 checks, ffmpeg cross-check). Port it to `ears` later if wanted.

**L-004 · 2026-09-25 · Cutting audio mid-waveform creates real inter-sample overs.**
A test sine that starts abruptly read up to +0.9 dB above its true amplitude.
That is band-limited reconstruction of a step (Gibbs ringing), not meter error.
With 50 ms fades the true-peak meter is exact to 0.0003 dB.
Change: exports for the Short need a fade-in and fade-out of at least a few milliseconds.

## Instrument calibration

**L-005 · 2026-09-25 · A compressor's attack knob is not its measured attack.**
The first reference compressor used a raw peak detector.
Set to 10 ms, it measured 17 ms; set to 1 ms, it measured 5 ms.
A sine's zero crossings made the gain computer chatter.
A 5 ms hold on the detector fixed it (now within 1 ms; release reads +5 ms, the hold).
Change: never trust knob labels. Measure Live's devices with `mlab probe` + `mlab comp-probe`.

**L-006 · 2026-09-25 · The first punch measure could not see compression.**
Version 1 compared a 2 ms envelope with a 100 ms envelope at onsets.
Limiting that cut crest factor by 5 dB moved it by 0.06 dB.
Version 2 measures hit peak (first 10 ms) minus body RMS (20–120 ms), on main hits only.
It is calibrated on a synthetic kick loop: slow attack raises it most; very fast attack raises it less (it still turns the body down); a limiter lowers it.
Change: `dynamics.transient_contrast_median_db` is now trustworthy on kick-led material. Recheck on real stems.

**L-007 · 2026-09-25 · A naive DC meter false-alarms on bass.**
The mean of 8 s of pink noise read -57 dBFS, above the -60 dBFS warning line.
That was low-frequency wander, not a steady offset.
Now DC is flagged only if it is consistent across 1 s blocks (z > 4).

**L-008 · 2026-09-25 · On a synthetic kick, punch peaked at 1–5 ms attack, not 30 ms.**
Hit-vs-body contrast: 12.8 dB dry; 15.3 dB at 0.1 ms; 21.4 dB at 1 ms; 21.9 dB at 5 ms; 20.7 dB at 30 ms.
The synthetic kick's body decays in 120 ms, so a 30 ms attack clamps part of the body too.
Change: the best attack depends on the kick's own envelope. Test it per kick, not per rule.

## HW002 one-minute demo (`HW002_1min-2026-08-13T2107.mp3`, 320 kb/s, 84 s)

**L-009 · 2026-09-25 · Baseline numbers.**
Integrated -13.8 LUFS. True peak -0.48 dBTP. PLR 13.4 dB. LRA 2.1 LU.
Short-term max -10.8 LUFS. Low-band (20–120 Hz) correlation 0.86.
ffmpeg's ebur128 agrees within 0.05 LU and 0.02 dB.
YouTube would turn it down by about 0.2 dB. There is no loudness left to gain there.

**L-010 · 2026-09-25 · The loudest peaks are in the breakdown, not on the kicks.**
The top peaks sit at 33.0–34.5 s (-0.5 to -1.3 dBFS).
The median beat peak is -6.3 dBFS; the 90th percentile is -4.2 dBFS.
So a limiter on this demo mostly shaves one breakdown event.
Evidence: H001. Limiting to -9 LUFS cost 5.4 dB of PLR but left block crest and hit contrast unchanged.
Change: tame the 33–34 s event at the source (clip or turn it down) before the master limiter.

**L-011 · 2026-09-25 · There is a steady negative offset while the kick plays.**
Per-second means sit near -0.018 of full scale (about -35 dBFS) in both channels.
In the breakdown (about 24–47 s) the mean is near zero.
Likely cause: asymmetric saturation in the kick or rumble chain (Decapitator, Dist COLDFIRE).
Removing it did NOT free headroom here (H003): the sample peak rose 0.1 dB.
The loudest peak is in the breakdown, where there is no offset.
Change: still high-pass at ~15 Hz for hygiene and limiter behaviour. Do not expect headroom from it.

**L-012 · 2026-09-25 · There is a low-mid hole.**
Band shares relative to total: bass (60–250 Hz) -2.7 dB, low-mid (250–500 Hz) -15.4 dB, mid (500 Hz–2 kHz) -8.8 dB.
A broad +3 dB bell at 350 Hz narrows it by 2.2 dB (H004).
Note 2 on the site warned about "a hole in the middle".
Change: needs references to judge. Absolute shares mean little without the genre's spread.

**L-013 · 2026-09-25 · AAC adds half a decibel of true peak.**
A 128 kb/s AAC round trip moved true peak from -0.48 to +0.03 dBTP (H006).
A master limited to -1.5 dBTP stayed at -1.43 dBTP after AAC.
Change: set the limiter to true-peak mode, ceiling -1.5 dBTP, for the Short.

**L-014 · 2026-09-25 · 16-bit dither is irrelevant for this demo.**
The quietest 100 ms blocks sit near -22 dBFS. The 16-bit TPDF floor is -96 dBFS.
There are no fades or silences for dither to matter in (H002).
Change: export 24-bit or 32-bit float; if a 16-bit file is ever needed, dither once, last.

**L-015 · 2026-09-25 · The Python compressor did not add punch to the demo.**
At matched loudness, 30 ms attack beat 0.1 ms by only 0.2 dB of hit contrast (H005).
Fast attack cost 3.8 dB of PLR; slow attack cost 1.0 dB.
The demo is already heavily processed; the reference compressor is not Glue Compressor.
Change: repeat with renders from Live (Glue Compressor, attack 0.3 / 3 / 30 ms) before believing this.

## Review fixes

**L-016 · 2026-09-25 · An independent review found four real faults; all fixed and now tested.**
1. `comp-probe` aligned the render by cross-correlating a steady tone. Plugin latency shifted it by whole cycles.
   Attack read 0.8 ms instead of 10 ms. Alignment now uses the tone's onset (calibration: 1024-sample latency recovered).
2. The `eq-diff` summary measured gains relative to 500 Hz–2 kHz, exactly where EQ moves usually are. Now absolute.
3. Silent files gave nonsense (+399 dB platform gain, premaster PASS). Now undefined values and a premaster FAIL.
4. The hypothesis `platform` op and `mlab deliver` used different normalisation rules. Now one model.
Also: predictions within rounding (0.015) of a strict threshold now read INCONCLUSIVE, not PASS/FAIL.

**L-017 · 2026-09-26 · Codec overs depend on the encoder, not just the codec.**
H006 on the container's ffmpeg 6.1.1 (native AAC encoder): true peak +0.51 dB after AAC 128 k.
H006 on the Mac mini's ffmpeg 4.4.2 (same settings): true peak -0.22 dB after AAC.
Same file, same bitrate, opposite sign. The -1.5 dBTP master stayed under 0 dBTP on both.
YouTube's own encoder is unknown to us.
Change: keep the -1.5 dBTP ceiling as a margin. Settle it by measuring a real upload.
