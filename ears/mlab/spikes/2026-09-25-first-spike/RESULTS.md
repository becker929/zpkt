# Mastering spike — results

All audio in `out/`. PLR = true peak minus LUFS (a crest-factor measure for loudness).

## Premaster (the raw test mix)

| file | LUFS | sample_peak | true_peak | PLR | crest |
|---|---|---|---|---|---|
| 00_premaster.wav | -20.8 | -6.0 | -5.59 | 15.2 | 15.5 |

## Exp 1 — loudness bias (identical audio, one is +1 dB)

| file | LUFS | sample_peak | true_peak | PLR | crest |
|---|---|---|---|---|---|
| 01_blind_X.wav | -19.0 | -4.23 | -3.81 | 15.2 | 15.5 |
| 01_blind_Y.wav | -20.0 | -5.23 | -4.81 | 15.2 | 15.5 |

## Exp 2 — two masters (limiter drive: gentle +7.0 dB, crushed +19.6 dB), then both turned to -14 LUFS like a streaming service

| file | LUFS | sample_peak | true_peak | PLR | crest |
|---|---|---|---|---|---|
| 02_master_gentle_-14LUFS.wav | -14.0 | -1.01 | -1.0 | 13.0 | 13.7 |
| 02_master_crushed_-9LUFS.wav | -9.0 | -0.11 | -0.1 | 8.9 | 9.6 |
| 02_gentle_after_normalization.wav | -14.0 | -1.0 | -1.0 | 13.0 | 13.7 |
| 02_crushed_after_normalization.wav | -14.0 | -5.11 | -5.1 | 8.9 | 9.6 |

## Exp 3 — inter-sample peaks

| file | sample_peak | true_peak | sample_peak_after | samples_over_0dBFS |
|---|---|---|---|---|
| 03_isp_sine.wav | -0.11 | 3.02 |  |  |
| crushed master → AAC 128k → decoded |  |  | 0.65 | 6 |
| gentle master → AAC 128k → decoded |  |  | -0.46 | 0 |

## Exp 4 — 16-bit reduction of a fading 1 kHz tone (error = output minus original)

| file | error_rms_dBFS | harmonic_share_of_error_dB |
|---|---|---|
| truncated | -95.1 | -9.5 |
| TPDF dithered | -96.3 | -21.1 |

## Exp 5 — compressor, 4:1, threshold -20 dBFS, 6 dB knee; every output level-matched to -21 LUFS

| file | LUFS | sample_peak | true_peak | PLR | crest | avg_GR_dB | max_GR_dB |
|---|---|---|---|---|---|---|---|
| 05_drums_dry.wav | -21.0 | -6.02 | -6.02 | 15.0 | 16.1 |  |  |
| 05_drums_fastA_fastR.wav | -21.0 | -4.78 | -4.24 | 16.8 | 16.2 | 2.2 | 10.1 |
| 05_drums_slowA_fastR.wav | -21.0 | -3.61 | -3.61 | 17.4 | 18.2 | 1.2 | 4.6 |
| 05_drums_fastA_slowR.wav | -21.0 | -3.04 | -2.91 | 18.1 | 18.6 | 6.0 | 10.1 |
| 05_drums_slowA_slowR.wav | -21.0 | -3.57 | -3.42 | 17.6 | 18.6 | 3.5 | 5.6 |
