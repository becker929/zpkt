# Subject 5 — Loudness war & metering (Ch. 17–19)

Keywords: LUFS, loudness normalization, true peak / inter-sample peaks, loudness war, crest factor.

## The idea in six sentences

LUFS measures loudness the way BS.1770 defines it: K-weighted, gated, averaged.
Streaming platforms turn loud tracks down to a target, often about -14 LUFS.
So pushing a master louder than the target buys nothing and costs peaks.
Peaks between samples can exceed the sample peak; true-peak meters find them.
Lossy codecs add more peak on top, so masters need a ceiling below 0 dBTP.
PLR and crest factor show how much a master was squashed.

## Instruments

| Command / key | Answers | Calibration |
|---|---|---|
| `mlab measure FILE` | integrated, momentary max, short-term max, LRA, sample peak, true peak, PLR, PSR | EBU Tech 3341 cases 1–5 within 0.03 LU; Tech 3342 cases 1–4 within 0.01 LU; ffmpeg ebur128 within 0.05 LU |
| true peak (8× oversampling) | peaks between samples | exact on a fs/4 sine (+3.01 dB) and an off-grid pulse; 60 random sines within 0.001 dB |
| `mlab deliver FILE` | what each platform does, and AAC/Opus round trips | platform model from reported behaviour (see below) |
| `dsp.master_to(x, sr, target, ceiling)` | a reference true-peak-limited master at a target loudness | limiter holds the ceiling within 0.05 dB |

## Platform targets (source tiers matter)

| Platform | Target | Turns quiet up? | Tier |
|---|---|---|---|
| YouTube (incl. Shorts, assumed) | about -14 LUFS | no | observed, reported by engineers (tier 4–6) |
| Spotify | -14 LUFS (normal) | yes, within peak headroom | Spotify documentation (tier 5) |
| Apple Music | about -16 LUFS | yes | reported (tier 5–6) |
| Instagram, TikTok | unknown | unknown | not documented; measure a real upload |

## HW002 baseline (L-009, L-010, L-013)

Integrated -13.8 LUFS, true peak -0.48 dBTP, PLR 13.4 dB, LRA 2.1 LU.
YouTube would turn it down 0.2 dB. AAC 128 k lifts its true peak to +0.03 dBTP.
The loudest peaks come from a breakdown event at 33–34.5 s.

## Experiments ready to run

- **H001** (done): -9 LUFS plays no louder on YouTube, costs 5.4 dB PLR. Hits kept their punch because the limiter mostly hit the breakdown event.
- **H006** (done): AAC adds 0.5 dB of true peak; a -1.5 dBTP ceiling survives.
- *Target sweep*: `master_to` at -14, -12, -10, -8 LUFS, each normalised to -14, ABX the extremes.
- *Opus vs AAC*: add `{op: codec, label: opus160}` variants when the ffmpeg build has libopus.

## Decisions this subject feeds

For the Short: integrated about -14 to -11 LUFS; true-peak limiter at -1.5 dBTP; check with `mlab deliver`.
Loudness beyond that is a sound choice (density), not a volume choice.

## Sources

- Primary: ITU-R BS.1770-5 (2023), algorithms for loudness and true peak (tier 1).
- Primary: EBU R 128 and EBU Tech 3341 / 3342 (tier 1). The calibration re-synthesises their test signals.
- Primary: AES TD1008 (2021), loudness for internet streaming (tier 5, industry recommendation).
- Secondary: Vickers, "The Loudness War: Background, Speculation and Recommendations", AES Convention Paper 8175, 2010 (tier 2).
- Reported YouTube behaviour: Critical Listening Lab, "YouTube loudness normalization" (tier 6).
