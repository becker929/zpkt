# Glossary

Terms used in this lab, in plain words. Standards named in brackets.

| Term | Meaning |
|---|---|
| **A/B** | Switching between two versions to compare them. |
| **ABX** | Blind test: hear A, hear B, then say whether unknown X is A or B. Guessing gets half right. |
| **AAC** | Lossy audio codec. YouTube serves AAC at about 128 kb/s alongside Opus. |
| **Attack / release** | How fast a compressor reacts when level rises (attack) and recovers when it falls (release). Here measured as time to 63 % of the change. |
| **Build / drop window** | The 16 bars before the drop (build) and the 16 bars from it (drop). `mlab target` compares mix and references window by window. |
| **Crest factor** | Peak level minus RMS level, in dB. A sine is 3 dB. High crest = spiky; low crest = dense. |
| **dB rel LUFS** | A band's power in dB minus the window's integrated loudness. It compares spectral shape, not level. |
| **dBFS** | Decibels relative to digital full scale. 0 dBFS is the largest sample value. |
| **dBTP** | Decibels true peak: the peak of the reconstructed analogue waveform, found by oversampling [BS.1770]. |
| **DC offset** | A constant shift of the waveform away from zero. Wastes headroom; causes clicks at edits. |
| **Dither** | Tiny added noise before reducing bit depth. It turns distortion from rounding into steady hiss. |
| **Effective bits** | How many bits the audio actually uses, whatever the container says. |
| **Equal-loudness contour** | The level each frequency needs to sound as loud as 1 kHz. Bass needs much more at low volume [ISO 226]. |
| **Gain staging** | Setting levels at each stage so nothing clips and nothing drowns in noise. |
| **Gating** | Ignoring near-silent blocks when computing loudness, so silence does not drag the number down [BS.1770]. |
| **Headroom** | The distance between the loudest peak and 0 dBFS. |
| **Inter-sample peak** | A peak between two samples, higher than either sample. Shows up after conversion or encoding. |
| **K-System** | Bob Katz's metering and monitoring scheme. K-20, K-14 and K-12 fix a monitor gain to a meter zero at -20, -14 or -12 dBFS RMS. |
| **K-weighting** | The filter BS.1770 applies before measuring loudness: a high shelf plus a low cut. |
| **Knee** | How gradually a compressor starts working around the threshold. 0 dB = hard knee. |
| **Level matching** | Setting two versions to equal loudness before comparing them. Louder sounds better otherwise. |
| **Limiter** | A compressor with a very high ratio and fast attack that stops peaks passing a ceiling. |
| **Loudness normalization** | A platform turning each track up or down to a target loudness. |
| **LRA (loudness range)** | Spread of short-term loudness between the 10th and 95th percentile, in LU [EBU Tech 3342]. |
| **LU** | Loudness unit: a 1 dB step in loudness. |
| **LUFS** | Loudness units relative to full scale [BS.1770]. Integrated = whole file; short-term = 3 s; momentary = 0.4 s. |
| **Macrodynamics** | Loudness change between sections: verse to drop, breakdown to peak. |
| **Microdynamics** | Level change inside a beat: the hit versus the body of a kick. |
| **Mid/side (M/S)** | Stereo split into the sum (mid) and difference (side) signals. |
| **Model check** | `eqfit`'s self-test: its no-move prediction against the measured stem sum, per band. The largest error says how far to trust a plan. |
| **Noise shaping** | Moving dither noise to frequencies where the ear is less sensitive, usually very high ones. |
| **Opus** | Lossy codec. YouTube serves Opus at about 130–160 kb/s. |
| **Outside the range** | How far a mix value sits outside the references' min–max range. 0 inside it; negative = under every reference. |
| **Parametric EQ** | EQ bands with adjustable frequency, gain and width (Q). |
| **Phon** | Loudness level: a sound is N phon if it is as loud as N dB SPL at 1 kHz. |
| **PLR** | Peak-to-loudness ratio: true peak minus integrated loudness. Low PLR = heavily limited. |
| **Premaster** | The mix file handed to mastering: no limiter on the main bus, headroom left. |
| **PSR** | Peak-to-short-term-loudness ratio, over 3 s windows. The minimum shows the most squashed passage. |
| **Punch (hit contrast)** | This lab's measure: peak of the first 10 ms after a hit minus RMS of 20–120 ms after it. |
| **Q** | Width of an EQ band. Higher Q = narrower. |
| **Reference track** | A finished release you compare against, at matched loudness. |
| **RMS** | Root mean square: average power as a level. |
| **Section contrast** | Integrated loudness of the drop window minus that of the build window, in LU. |
| **Shelving EQ** | EQ that raises or lowers everything above (high shelf) or below (low shelf) a frequency. |
| **Side minus mid** | Side energy minus mid energy in one band, in dB. Very negative = mono there; 0 dB = as wide as two unrelated channels. |
| **Signal flow** | The path audio takes through tracks, groups, sends and the main bus. |
| **Stem** | A solo render of one bus. A mix's stems sum to about the mix (L-018). |
| **TPDF / RPDF** | Triangular / rectangular probability dither. TPDF removes noise modulation; it is the default. |
| **Transfer function** | What a device does to each frequency; `eq-diff` measures it from dry and wet files. |
| **Truncation** | Cutting off low bits without dither. Makes distortion on quiet material. |
| **Word length** | Bit depth: 16, 24 or 32-bit float. |
| **FFT bin** | One frequency step of a spectrum. Its width is the sample rate over the segment length. |
| **Welch segment** | One short slice of a file whose spectrum is taken. A Welch PSD averages many of them. |
| **Trapezoid** | Summing a curve by straight lines between its points. Used to add up the bins in a band. |
| **Crossover** | A filter pair that splits audio into bands that sum back to the whole. |

**Peak window.** The ~30 s stretch, on the bar grid, with the most 2–16 kHz energy while the kick plays. `mlab refs --peaks` compares peak windows so intros and breaks do not dilute the comparison.

**Kickless run.** Two or more bars whose sub-100 Hz energy is at least 8 dB under the track median. The longest one after the intro is the main break.
