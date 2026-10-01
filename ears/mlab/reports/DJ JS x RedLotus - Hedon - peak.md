# Measurement sheet — DJ JS x RedLotus - Hedon - peak.wav

30.389 s · 48000 Hz · 2 ch · PCM_24

## Loudness (Ch. 17-19)

| measure | value |
|---|---|
| integrated | -4.95 |
| momentary_max | -4.1 |
| short_term_max | -4.56 |
| lra | 1.96 |
| lra_low | -6.54 |
| lra_high | -4.58 |
| sample_peak | -1.01 |
| true_peak | 0.01 |
| plr | 4.96 |
| psr_min | 3.57 |

## Dynamics (Ch. 5-7)

| measure | value |
|---|---|
| crest_db | 4.94 |
| plr_db | 4.96 |
| psr_min_db | 3.57 |
| k20_rms_db | 17.06 |
| k14_rms_db | 11.06 |
| lra_lu | 1.96 |
| short_term_p95_minus_p10 | 1.96 |
| short_term_max_minus_integrated | 0.39 |
| block_crest_median_db | 4.58 |
| block_crest_p10_db | 4.45 |
| block_crest_p90_db | 6.96 |
| onsets | 151 |
| transient_contrast_median_db | 4.02 |

## Tonal balance (Ch. 4)

| measure | value |
|---|---|
| slope_db_per_oct | -3.9 |
| centroid_hz | 282.0 |
| group.sub | -9.16 |
| group.bass | -1.42 |
| group.low_mid | -21.39 |
| group.mid | -13.24 |
| group.upper_mid | -16.04 |
| group.presence | -19.45 |
| group.air | -26.36 |

1/3-octave levels (dB, relative):

25:-41.78 31:-33.5 39:-27.19 50:-18.82 63:-12.16 79:-12.75 100:-12.73 125:-21.89 158:-29.97 199:-33.21 251:-28.33 316:-32.54 398:-35.17 501:-32.87 631:-28.6 794:-26.04 1000:-25.73 1258:-26.08 1584:-27.58 1995:-27.38 2511:-26.27 3162:-26.65 3981:-28.97 5011:-29.25 6309:-30.49 7943:-32.78 10000:-36.03 12589:-41.46 15848:-47.34 19952:-51.0

## Stereo

| band Hz | correlation | side−mid dB |
|---|---|---|
| 20–120 | 1.0 | -43.59 |
| 120–500 | 0.96 | -16.85 |
| 500–2000 | 0.637 | -6.53 |
| 2000–8000 | 0.438 | -4.08 |
| 8000–20000 | 0.573 | -5.66 |

## Word length (Ch. 15)

- container: PCM_24
- effective bits: 16
- verdict: 24-bit container holding 16-bit audio: re-exported from a 16-bit source?; programme never gets quiet enough to see the floor: dither not observable (masked); DC offset -55.64 dBFS: high-pass or DC-block before mastering

## Delivery (YouTube and others)

| platform | gain dB | plays at LUFS | plays at dBTP | note |
|---|---|---|---|---|
| youtube | -9.05 | -14.0 | -9.04 | observed; applies to uploads incl. Shorts (assumed) |
| spotify | -9.05 | -14.0 | -9.04 | documented by Spotify; up-gain limited by peak headroom |
| apple_music | -11.05 | -16.0 | -11.04 | Sound Check; reported |
| tidal | -9.05 | -14.0 | -9.04 | reported |
| amazon_music | -9.05 | -14.0 | -9.04 | reported, varies |
| soundcloud | 0.0 | -4.95 | 0.01 | no normalisation reported |
| instagram | 0.0 | -4.95 | 0.01 | undocumented; measure a real upload |
| tiktok | 0.0 | -4.95 | 0.01 | undocumented; measure a real upload |

Advice:
- YouTube turns this down 9.05 dB; loudness above -14 LUFS buys nothing there
- true peak above -1 dBTP: expect codec overs; lower the limiter ceiling
