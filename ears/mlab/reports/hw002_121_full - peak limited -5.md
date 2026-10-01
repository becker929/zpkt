# Measurement sheet — hw002_121_full - peak limited -5.wav

30.011 s · 44100 Hz · 2 ch · PCM_24

## Loudness (Ch. 17-19)

| measure | value |
|---|---|
| integrated | -6.69 |
| momentary_max | -6.22 |
| short_term_max | -6.55 |
| lra | 0.31 |
| lra_low | -6.87 |
| lra_high | -6.56 |
| sample_peak | -0.3 |
| true_peak | -0.3 |
| plr | 6.39 |
| psr_min | 6.25 |

## Dynamics (Ch. 5-7)

| measure | value |
|---|---|
| crest_db | 7.6 |
| plr_db | 6.39 |
| psr_min_db | 6.25 |
| k20_rms_db | 15.11 |
| k14_rms_db | 9.11 |
| lra_lu | 0.31 |
| short_term_p95_minus_p10 | 0.31 |
| short_term_max_minus_integrated | 0.14 |
| block_crest_median_db | 7.54 |
| block_crest_p10_db | 7.33 |
| block_crest_p90_db | 7.82 |
| onsets | 70 |
| transient_contrast_median_db | 7.48 |

## Tonal balance (Ch. 4)

| measure | value |
|---|---|
| slope_db_per_oct | -4.25 |
| centroid_hz | 544.0 |
| group.sub | -7.8 |
| group.bass | -1.71 |
| group.low_mid | -16.8 |
| group.mid | -16.35 |
| group.upper_mid | -20.49 |
| group.presence | -15.19 |
| group.air | -16.7 |

1/3-octave levels (dB, relative):

25:-49.09 31:-42.46 39:-32.23 50:-20.49 63:-14.65 79:-13.87 100:-17.4 125:-20.47 158:-22.15 199:-23.36 251:-27.0 316:-30.02 398:-30.23 501:-30.69 631:-32.17 794:-30.32 1000:-32.36 1258:-32.48 1584:-32.87 1995:-34.81 2511:-35.08 3162:-33.22 3981:-31.22 5011:-28.45 6309:-26.46 7943:-27.13 10000:-28.33 12589:-32.97 15848:-35.71

## Stereo

| band Hz | correlation | side−mid dB |
|---|---|---|
| 20–120 | 0.863 | -11.32 |
| 120–500 | 0.943 | -15.28 |
| 500–2000 | 0.733 | -8.12 |
| 2000–8000 | 0.738 | -8.19 |
| 8000–20000 | 0.834 | -10.39 |

## Word length (Ch. 15)

- container: PCM_24
- effective bits: 24
- verdict: programme never gets quiet enough to see the floor: dither not observable (masked); DC offset -27.7 dBFS: high-pass or DC-block before mastering

## Delivery (YouTube and others)

| platform | gain dB | plays at LUFS | plays at dBTP | note |
|---|---|---|---|---|
| youtube | -7.31 | -14.0 | -7.61 | observed; applies to uploads incl. Shorts (assumed) |
| spotify | -7.31 | -14.0 | -7.61 | documented by Spotify; up-gain limited by peak headroom |
| apple_music | -9.31 | -16.0 | -9.61 | Sound Check; reported |
| tidal | -7.31 | -14.0 | -7.61 | reported |
| amazon_music | -7.31 | -14.0 | -7.61 | reported, varies |
| soundcloud | 0.0 | -6.69 | -0.3 | no normalisation reported |
| instagram | 0.0 | -6.69 | -0.3 | undocumented; measure a real upload |
| tiktok | 0.0 | -6.69 | -0.3 | undocumented; measure a real upload |

Advice:
- YouTube turns this down 7.31 dB; loudness above -14 LUFS buys nothing there
- true peak above -1 dBTP: expect codec overs; lower the limiter ceiling
