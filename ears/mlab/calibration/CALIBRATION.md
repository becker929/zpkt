# Calibration report

Generated 2026-09-26 00:59 by `python3 -m mlab calibrate`.
**94 / 94 checks pass.**

Basis: EBU-3341/3342 and BS.1770 = published test cases, re-synthesised; analytic = closed-form; self-consistency = recovers a known processor; cross-check = independent implementation; planted fault = a defect inserted on purpose.

| instrument | case | expected | measured | tol | ok | basis |
|---|---|---|---|---|---|---|
| premaster | all-zero file: overall | FAIL | FAIL | 0 | ✅ | planted fault |
| delivery | all-zero file: no platform gain invented | True | True | 0 | ✅ | planted fault |
| loudness | 1 s file: LRA undefined (needs > 3 s) | True | True | 0 | ✅ | EBU-3342 |
| loudness | K-weighting stage 1 coefficients @48k (max abs err) | 0.0 | 0.0 | 1e-08 | ✅ | BS.1770 |
| loudness | K-weighting stage 2 coefficients @48k (max abs err) | 0.0 | 0.0 | 1e-08 | ✅ | BS.1770 |
| loudness | integrated, Tech 3341 case 1: -23 dBFS 20 s | -23.0 | -22.9933 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated, Tech 3341 case 2: -33 dBFS 20 s | -33.0 | -32.9933 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated, Tech 3341 case 3: -36/-23/-36 | -23.0 | -23.0139 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated, Tech 3341 case 4: -72/-36/-23/-36/-72 | -23.0 | -23.0139 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated, Tech 3341 case 5: -26/-20/-26 x 20.1 s | -23.0 | -22.9859 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated case 1 at 44100 Hz | -23.0 | -22.9905 | 0.1 | ✅ | EBU-3341 |
| loudness | integrated case 1 at 96000 Hz | -23.0 | -23.0106 | 0.1 | ✅ | EBU-3341 |
| loudness | momentary max, steady -23 tone | -23.0 | -22.9933 | 0.1 | ✅ | EBU-3341 |
| loudness | short-term max, steady -23 tone | -23.0 | -22.9933 | 0.1 | ✅ | EBU-3341 |
| loudness | LRA, Tech 3342 case 1: -20/-30 | 10 | 10.0 | 1.0 | ✅ | EBU-3342 |
| loudness | LRA, Tech 3342 case 2: -20/-15 | 5 | 5.0 | 1.0 | ✅ | EBU-3342 |
| loudness | LRA, Tech 3342 case 3: -40/-20 | 20 | 20.0 | 1.0 | ✅ | EBU-3342 |
| loudness | LRA, Tech 3342 case 4: -50/-35/-20/-35/-50 | 15 | 15.0 | 1.0 | ✅ | EBU-3342 |
| true peak | fs/4 sine at 45°: TP - sample peak | 3.0103 | 3.0102 | 0.05 | ✅ | analytic |
| true peak | isolated band-limited pulse, peak between samples | -0.9151 | -0.9252 | 0.1 | ✅ | analytic |
| true peak | same pulse: sample peak under-reads by > 0.3 dB | True | True | 0 | ✅ | analytic |
| true peak | 60 random full-scale sines 0.02-0.45 fs: worst |error| dB | 0.0 | 0.0002 | 0.1 | ✅ | analytic |
| true peak | reference limiter holds -1 dBTP on hot pink noise (TP) | -1.0 | -1.0 | 0.05 | ✅ | self-consistency |
| dynamics | crest factor of a sine (dB) | 3.0103 | 3.0102 | 0.01 | ✅ | analytic |
| dynamics | crest factor of a square wave (dB) | 0.0 | 0.0001 | 0.01 | ✅ | analytic |
| dynamics | gain computer: 10 dB over, 4:1 -> 7.5 dB GR | 7.5 | 7.5 | 1e-09 | ✅ | analytic |
| dynamics | punch: slow-attack comp raises hit-vs-body contrast (> +2 dB) | True | True | 0 | ✅ | self-consistency |
| dynamics | punch: 0.1 ms attack gives > 3 dB less contrast than 30 ms | True | True | 0 | ✅ | self-consistency |
| dynamics | punch: 12 dB into a limiter lowers contrast (> 2 dB) | True | True | 0 | ✅ | self-consistency |
| comp-probe | 1024-sample plugin latency found by onset alignment | 1024 | 1024 | 0 | ✅ | self-consistency |
| comp-probe | attack ms with 1024-sample latency (10 ms set) | 10 | 10.6 | 2.0 | ✅ | self-consistency |
| comp-probe | release ms with 1024-sample latency (100 ms set) | 100 | 104.9 | 20.0 | ✅ | self-consistency |
| comp-probe | threshold, thr -30 / 4:1 / knee 6 / A 10 ms / R 100 ms | -30 | -30.0 | 1.5 | ✅ | self-consistency |
| comp-probe | ratio, thr -30 / 4:1 / knee 6 / A 10 ms / R 100 ms | 4 | 3.98 | 0.6 | ✅ | self-consistency |
| comp-probe | attack ms, thr -30 / 4:1 / knee 6 / A 10 ms / R 100 ms | 10 | 10.6 | 2.0 | ✅ | self-consistency |
| comp-probe | release ms, thr -30 / 4:1 / knee 6 / A 10 ms / R 100 ms | 100 | 104.9 | 20.0 | ✅ | self-consistency |
| comp-probe | threshold, thr -18 / 2:1 / knee 0 / A 1 ms / R 50 ms | -18 | -18.0 | 1.5 | ✅ | self-consistency |
| comp-probe | ratio, thr -18 / 2:1 / knee 0 / A 1 ms / R 50 ms | 2 | 2.0 | 0.3 | ✅ | self-consistency |
| comp-probe | attack ms, thr -18 / 2:1 / knee 0 / A 1 ms / R 50 ms | 1 | 1.3 | 2.0 | ✅ | self-consistency |
| comp-probe | release ms, thr -18 / 2:1 / knee 0 / A 1 ms / R 50 ms | 50 | 55.0 | 10.0 | ✅ | self-consistency |
| comp-probe | threshold, thr -24 / 8:1 / knee 10 / A 30 ms / R 300 ms | -24 | -24.0 | 1.5 | ✅ | self-consistency |
| comp-probe | ratio, thr -24 / 8:1 / knee 10 / A 30 ms / R 300 ms | 8 | 7.67 | 1.2 | ✅ | self-consistency |
| comp-probe | attack ms, thr -24 / 8:1 / knee 10 / A 30 ms / R 300 ms | 30 | 30.5 | 6.0 | ✅ | self-consistency |
| comp-probe | release ms, thr -24 / 8:1 / knee 10 / A 30 ms / R 300 ms | 300 | 303.9 | 60.0 | ✅ | self-consistency |
| spectrum | pink noise density slope (dB/oct) | -3.01 | -2.94 | 0.3 | ✅ | analytic |
| spectrum | pink noise 1/3-oct band spread 100 Hz-10 kHz (max-min dB) | 0.0 | 0.77 | 1.5 | ✅ | analytic |
| spectrum | 1 kHz sine lands in the 1 kHz band (> 30 dB above neighbours) | True | True | 0 | ✅ | analytic |
| eq-diff | recovered EQ gain at 40 Hz | -3.8863 | -3.8843 | 0.3 | ✅ | self-consistency |
| eq-diff | recovered EQ gain at 100 Hz | -1.9348 | -1.9291 | 0.3 | ✅ | self-consistency |
| eq-diff | recovered EQ gain at 1000 Hz | 6.0001 | 5.9557 | 0.3 | ✅ | self-consistency |
| eq-diff | recovered EQ gain at 3000 Hz | 0.7956 | 0.7985 | 0.3 | ✅ | self-consistency |
| eq-diff | recovered EQ gain at 12000 Hz | 2.7567 | 2.7521 | 0.3 | ✅ | self-consistency |
| equal-loudness | ISO 226 contour at 1 kHz equals 40 phon | 40.0 | 40.01 | 0.05 | ✅ | ISO 226 |
| equal-loudness | ISO 226 contour at 1 kHz equals 60 phon | 60.0 | 60.0116 | 0.05 | ✅ | ISO 226 |
| equal-loudness | ISO 226 contour at 1 kHz equals 80 phon | 80.0 | 80.0121 | 0.05 | ✅ | ISO 226 |
| equal-loudness | 40 phon needs more SPL at 50 Hz than at 1 kHz (> +20 dB) | True | True | 0 | ✅ | ISO 226 |
| stereo | polarity-inverted channels: low-band correlation | -1.0 | -1.0 | 0.01 | ✅ | analytic |
| bitdepth | effective bits of a 16-bit quantised signal | 16 | 16 | 0 | ✅ | analytic |
| bitdepth | effective bits of a 24-bit quantised signal | 24 | 24 | 0 | ✅ | analytic |
| bitdepth | effective bits of float noise (> 24) | 32 | 32 | 0 | ✅ | analytic |
| bitdepth | 16-bit error floor, none (dBFS rms) | -101.1008 | -101.0966 | 0.2 | ✅ | analytic |
| bitdepth | 16-bit error floor, rpdf (dBFS rms) | -98.0905 | -98.0852 | 0.2 | ✅ | analytic |
| bitdepth | 16-bit error floor, tpdf (dBFS rms) | -96.3296 | -96.3236 | 0.2 | ✅ | analytic |
| bitdepth | truncation puts >8 dB more of its error at harmonics than TPDF | True | True | 0 | ✅ | analytic |
| bitdepth | noise-shaped dither error rises > 6 dB toward HF | True | True | 0 | ✅ | analytic |
| premaster | clean 24-bit mix with fades: overall | PASS | PASS | 0 | ✅ | planted fault |
| premaster | 10 samples at full scale: clipped_runs | FAIL | FAIL | 0 | ✅ | planted fault |
| premaster | DC offset -40 dBFS: dc_offset_dbfs | WARN | WARN | 0 | ✅ | planted fault |
| premaster | one channel polarity-inverted: correlation | FAIL | FAIL | 0 | ✅ | planted fault |
| premaster | clipped/limited main bus (PLR < 8): plr_db | WARN | WARN | 0 | ✅ | planted fault |
| premaster | no fade-out: tail_last_10ms_dbfs | WARN | WARN | 0 | ✅ | planted fault |
| premaster | 16-bit export: format | WARN | WARN | 0 | ✅ | planted fault |
| compare | loudness match: |LUFS A - LUFS B| | 0.0 | 0.0 | 0.01 | ✅ | analytic |
| compare | ABX: P(>=10 of 12 by guessing) | 0.0193 | 0.0193 | 0.0001 | ✅ | analytic |
| compare | ABX: P(>=9 of 12 by guessing) | 0.073 | 0.073 | 0.0001 | ✅ | analytic |
| delivery | YouTube gain for a -8 LUFS master | -6.0 | -6.0 | 1e-09 | ✅ | platform model |
| delivery | YouTube leaves a -20 LUFS master alone | 0.0 | 0.0 | 1e-09 | ✅ | platform model |
| delivery | AAC round-trip time-aligned (correlation below 4 kHz) | 1.0 | 0.9913 | 0.02 | ✅ | self-consistency |
| als | Live 12 set: tempo read from MainTrack | 120.0 | 120.0 | 0 | ✅ | fixture |
| als | Live 10 set: tempo read from MasterTrack | 140.0 | 140.0 | 0 | ✅ | fixture |
| als | planted Limiter on main bus is flagged | True | True | 0 | ✅ | planted fault |
| als | planted switched-off Decapitator is flagged | True | True | 0 | ✅ | planted fault |
| loudness | integrated vs pyloudnorm: pink -20 dBFS | -18.8389 | -18.7973 | 0.1 | ✅ | cross-check |
| loudness | integrated vs ffmpeg ebur128: pink -20 dBFS | -18.8 | -18.7973 | 0.2 | ✅ | cross-check |
| loudness | LRA vs ffmpeg ebur128: pink -20 dBFS | 0.0 | 0.056 | 0.5 | ✅ | cross-check |
| true peak | TP vs ffmpeg ebur128: pink -20 dBFS | -5.4 | -5.4213 | 0.3 | ✅ | cross-check |
| loudness | integrated vs pyloudnorm: EBU 3342 case 4 | -24.5333 | -24.4919 | 0.1 | ✅ | cross-check |
| loudness | integrated vs ffmpeg ebur128: EBU 3342 case 4 | -24.5 | -24.4919 | 0.2 | ✅ | cross-check |
| loudness | LRA vs ffmpeg ebur128: EBU 3342 case 4 | 15.0 | 15.0 | 0.5 | ✅ | cross-check |
| true peak | TP vs ffmpeg ebur128: EBU 3342 case 4 | -20.0 | -20.0 | 0.3 | ✅ | cross-check |
| loudness | integrated vs pyloudnorm: HW002_1min-2026-08-13T2107.mp3 | -13.8824 | -13.8408 | 0.1 | ✅ | cross-check |
| loudness | integrated vs ffmpeg ebur128: HW002_1min-2026-08-13T2107.mp3 | -13.8 | -13.8408 | 0.2 | ✅ | cross-check |
| loudness | LRA vs ffmpeg ebur128: HW002_1min-2026-08-13T2107.mp3 | 2.1 | 2.0801 | 0.5 | ✅ | cross-check |
| true peak | TP vs ffmpeg ebur128: HW002_1min-2026-08-13T2107.mp3 | -0.5 | -0.4827 | 0.3 | ✅ | cross-check |
