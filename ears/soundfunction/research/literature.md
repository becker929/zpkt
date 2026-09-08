# Literature sweep: the structural role of sounds in modern hard techno

*Scope: 2018+ hard techno (145–160 BPM, kick/rumble-driven). Compiled 2026-09-05 by a
research assistant model under direction; every source below was opened, and its URL is given.
Source tiers follow the project's hierarchy: 1 reproduced science, 2 peer-reviewed,
3 reference work, 4 named expert practitioner, 5 industry, 6 other.*

## 1. Timbre and sound-role perception

**Grey, J.M. (1977), "Multidimensional perceptual scaling of musical timbres," *JASA* 61(5):1270.** Tier 1/2.
http://sites.music.columbia.edu/cmc/courses/g6610/fall2019/week3/Grey_1977_Multidimensional_perceptual_scaling_of_musical_timbres.pdf ;
https://pubs.aip.org/asa/jasa/article/61/5/1270/626725
Foundational MDS study: 16 instrument tones separate along three axes correlated with (1) spectral energy distribution, (2) spectral flux / synchronicity of harmonic onsets, (3) low-amplitude high-frequency energy during the attack. Timbre discrimination is driven by a small number of spectro-temporal dimensions, not a single "brightness" scale.

**Lakatos, S. (2000), "A common perceptual space for harmonic and percussive timbres," *Perception & Psychophysics* 62(7).** Tier 2.
https://link.springer.com/article/10.3758/BF03212144
Directly on percussive sounds: spectral centroid and rise time (attack) are the two principal perceptual dimensions for both pitched and percussive timbres, robust across musicians and non-musicians. Listeners increasingly group percussive sounds by inferred sound source using centroid + attack as primary cues.

**Peeters, G., Giordano, B., Susini, P., Misdariis, N., McAdams, S. (2011), "The Timbre Toolbox," *JASA* 130(5):2902.** Tier 1/2.
https://www.mcgill.ca/mpcl/files/mpcl/peeters_2011_jasa.pdf
Defines >100 spectral/temporal/harmonic descriptors (centroid, spread, skewness, kurtosis, slope, attack time via the "weakest-effort" method, spectral flux, harmonic-to-noise ratio) and shows they reduce to ~10 relatively independent classes. The standard toolbox drum/EDM classification papers build on.

**Siedenburg, K. & McAdams, S. (2017), "Four Distinctions for the Auditory 'Wastebasket' of Timbre," *Music Perception*; McAdams & Siedenburg (2019).** Tier 2/3.
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5632649/ ; https://www.mcgill.ca/mpcl/files/mpcl/mcadams_2019_foundmuspsychol.pdf
"Timbre" bundles distinct sub-attributes (source identification, brightness/spectral envelope, temporal envelope, noise/texture) that should be measured separately — a caution against reducing a sound's role to a single feature.

**Herrera, P., Yeterian, A., Gouyon, F. (2002), "Automatic Classification of Drum Sounds," ICMAI 2002.** Tier 2.
https://link.springer.com/chapter/10.1007/3-540-45722-4_8
From ~50 descriptors, ~20 (centroid, spectral shape, log-attack-time, temporal centroid, zero-crossing, MFCC-like bands) are most discriminative for kick / snare / hihat / toms / cymbals with cross-validated classifiers.

## 2. Groove, entrainment, and rhythmic role

**Witek, M.A.G. et al. (2014), "Syncopation, Body-Movement and Pleasure in Groove Music," *PLoS ONE* 9(4):e94446.** Tier 1/2.
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3989225/
Medium syncopation against a low-frequency pulse produces the highest wanting-to-move and pleasure ratings (inverted U). Syncopation-against-pulse is a measurable, perceptually consequential rhythmic-role variable.

**Danielsen, A. (ed.) (2010), *Musical Rhythm in the Age of Digital Reproduction*, Ashgate/Routledge.** Tier 3.
https://www.routledge.com/Musical-Rhythm-in-the-Age-of-Digital-Reproduction/Danielsen/p/book/9781138246843
Argues timbre/sound quality is a constituent of groove, treats body movement as integral to rhythmic analysis, and covers house/techno production directly.

**Zeiner-Henriksen, H.T. (2010), "Moved by the Groove: Bass Drum Sounds and Body Movements in Electronic Dance Music,"** in the Danielsen volume, pp.121–139. Tier 3/4.
https://www.researchgate.net/publication/291171696
The "poum-tchak" pattern: the kick ("poum") articulates the downstroke of the dancer's movement, the hi-hat ("tchak") the upstroke — an explicit mapping of kick vs hi-hat to phases of embodied entrainment.

**Brøvig-Hanssen, R., Sandvik, B.E., Aareskjold-Drecker, J.M. (2020), "Dynamic Range Processing and Its Influence on Perceived Timing in Electronic Dance Music," *Music Theory Online* 26(2).** Tier 2/3.
https://www.mtosmt.org/issues/mto.20.26.2/mto.20.26.2.brovighanssen.html
Directly on sidechain compression (the mechanism behind the rumble): kick-triggered ducking extends other sounds' rise time, delays their perceptual centre (P-centre), and makes them feel "pushed off the beat". Producers interviewed treat pumping as a core groove parameter.

**Repp, B.H. (2008), "A filled duration illusion in music: Effects of metrical subdivision on the perception and production of beat tempo."** Tier 1/2.
https://pmc.ncbi.nlm.nih.gov/articles/PMC2916667/
Metrical subdivision slows *perceived* tempo relative to the same interval left empty. Relevant to why hi-hat subdivision density is a candidate "drive" parameter independent of BPM. Not tested on techno — flagged as inference.

## 3. MIR features for percussive / EDM structural classification

**Wu, C-W. et al. (2018), "A Review of Automatic Drum Transcription," *IEEE/ACM TASLP*.** Tier 2.
https://www.open-access.bcu.ac.uk/6180/1/Wu-et-al.-2018-A-review-of-automatic-drum-transcription.pdf
Surveys onset-detection + classification pipelines; MFCCs, spectral-flux onset functions and envelope descriptors are the standard feature set for identifying drum-type events.

**Datasets.** IDMT-SMT-Drums (608 files, kick/snare/hihat loops) https://www.idmt.fraunhofer.de/en/publications/datasets/drums.html ; ENST-Drums https://www.researchgate.net/publication/220722919 . Tier 3. Neither contains distorted techno kicks or rumble layers.

**Panteli, M., Bogaards, N., Honingh, A. (2014), "Modeling Rhythm Similarity for Electronic Dance Music," ISMIR 2014**; extended as Panteli et al. (2017), *Musicae Scientiae*. Tier 2.
https://archives.ismir.net/ismir2014/paper/000268.pdf
Rhythm- and timbre-similarity models for EDM from onset-pattern and spectral features; spectral + rhythmic vectors meaningfully separate EDM subgenres.

**Yadati, K., Larson, M., Liem, C.C.S., Hanjalic, A. (2014), "Detecting Drops in Electronic Dance Music," ISMIR 2014.** Tier 2.
https://archives.ismir.net/ismir2014/paper/000297.pdf
Spectrogram, MFCC and rhythm features into an SVM to detect drops: drops are acoustically well-defined events (spectral + energy + rhythmic-density signature).

**Kim, T. et al. (2024/2025), "Raveform: A Dataset of Metrical and Functional Structure Annotations for EDM Tracks in DJ Mixes," *TISMIR* 9(1):131–143.** Tier 2.
https://transactions.ismir.net/articles/10.5334/tismir.288
1,423 tracks annotated by three experts with EDM-specific functional section labels: Intro, Buildup, Breakdown, Drop, Cooldown, Bridge, Outro. Pop-trained segmentation models transfer poorly to EDM.

**Zehren, M., Alunno, M., Bientinesi, P. (2024), "Interpretability of Methods for Switch Point Detection in Electronic Dance Music," *Signals* 5(4):36.** Tier 2.
https://www.mdpi.com/2624-6120/5/4/36
The most impactful interpretable features for structural switch points in EDM: energy novelty, timbral (spectral) novelty, number of drum onsets, harmonic novelty. The closest peer-reviewed match to "measurable parameters that mark a change in structural role", at the section level.

**Ziemer, T. & Linke, S. (2024), "An Audio-Perspective on the Divergent Paths of Techno in Germany and the United States," *TISMIR* 9(1):264–279.** Tier 2.
https://transactions.ismir.net/articles/10.5334/tismir.324
The only MIR paper found that analyses techno by name, using BPM, phase space, channel correlation and crest factor as track-level descriptors, 1984–1994. Crest factor is directly relevant to separating transient sounds (kick, clap) from sustained ones (pad, rumble). Not post-2018, not sound-level.

## 4. Production theory (named practitioners — tier 4/5)

**Attack Magazine, "Dark Techno Rumble" (Beat Dissected), 2019.** Tier 5.
https://www.attackmagazine.com/technique/beat-dissected/dark-techno-rumble/
A compressed 909-style kick with pronounced pitch envelope as foundation; the rumble is a *second* kick through long reverb, low-passed, with the kick itself high-passed below ~50 Hz and dipped ~3 dB at 500 Hz; sidechain applied to rumble *and* hats so every layer ducks on the kick; drive and resonance add mid grit to hats.

**MusicRadar, "Create a rumbling techno kick in 10 easy steps."** Tier 5.
https://www.musicradar.com/how-to/rumbling-techno-kick
Confirms the two-layer kick + rumble architecture (EQ, delay/reverb, distortion, compression) as standard.

**MusicRadar, "Perc: 5 things I've learned about music production," Matt Mullen, 17 Nov 2021.** Tier 4 (Ali Wells / Perc).
https://www.musicradar.com/news/perc-5-things-ive-learned-in-music-production
Kicks from 2–3 layers at most, phase-aligned; transients "barely noticeable… just a bit of attack and click". Automating sidechain ratio to loosen pumping before a breakdown as an alternative to risers.

**Attack Magazine, "Perc: In The Studio."** Tier 4.
https://www.attackmagazine.com/features/interview/perc-in-the-studio/
Layered, individually distorted/compressed/EQ'd percussion hits; texture built additively from processed layers.

**Decoded Magazine (2017), Klangkuenstler interview.** Tier 4.
https://www.decodedmagazine.com/klangkuenstler-interview-2017/
States a preference for "punchy and dirty drums". Thin — a single short quote.

**Not found:** first-person written production statements from Nico Moreno, I Hate Models, 999999999 or SNTS; only third-party tutorial videos (tier 6), excluded.

## 5. Musical form in techno

**Butler, M.J. (2006), *Unlocking the Groove*, Indiana University Press.** Tier 3.
https://archive.org/details/unlockinggroover00butl
Dance-floor "structural intersections" are felt via hypermetric orientation at 16- or 32-bar spans; phrase length gates when role changes may occur.

**Iler, D. (2011), "Formal Devices of Trance and House Music: Breakdowns, Buildups and Anthems," MM thesis, UNT.** Tier 3.
https://digital.library.unt.edu/ark:/67531/metadc103332/
Transcribes 22 tracks; breakdown/buildup/anthem as one tension-and-release gesture; the buildup is marked when bass/snare/hihat re-articulate the downbeat after being stripped out.

**Solberg, R.T. & Steinsvik, W. (2015), "Waiting for the Bass to Drop," *Dancecult* 6(1):61–82.** Tier 2/3.
https://dj.dancecult.net/index.php/dancecult/article/download/451/457
Correlates production techniques in build-up and drop sections with peak emotional intensity. **Full text could not be parsed in this session; cited from the abstract only.**

**Solberg, R.T. & Jensenius, A.R. (2019), motion-capture study of dancers through breakdown → buildup → drop.** Tier 2.
https://eprints.whiterose.ac.uk/id/eprint/145911/1/Solberg&Dibben2019.pdf
Quantity of motion dips then surges with the arrangement's energy trajectory: the role sequence has a measurable behavioural correlate.

**Garcia, L-M. (2015), "Beats, Flesh, and Grain: Sonic Tactility and Affect in Electronic Dance Music," *Sound Studies* 1(1).** Tier 2/3.
https://www.tandfonline.com/doi/full/10.1080/20551940.2015.1079072
Low-frequency weight and "grain"/noisiness as deliberate, perceptually targeted design parameters. Ethnographic, not acoustically measured.

## Candidate parameters

| # | Parameter | Measures | Roles it separates | Sources | Confidence |
|---|---|---|---|---|---|
| 1 | Attack time / log-attack time | Rise from onset to peak | Kick (short) vs pad (long) vs stab (short–medium) | Grey 1977; Lakatos 2000; Peeters 2011; Herrera 2002 | High |
| 2 | Spectral centroid | Brightness | Hats/cymbals (high) vs kick/rumble (low) vs clap (mid-high, noisy) | Grey; Lakatos; Peeters; Herrera | High |
| 3 | Spectral flux / novelty | Rate of spectral change | Transitions/impacts (high) vs steady texture (low) | Grey (axis II); Zehren 2024 | High (section level); moderate (sound level) |
| 4 | Noisiness / HNR / flatness | Noise vs tone | Hats, clap, riser (noisy) vs kick, sub, stab (tonal) | Peeters; Herrera; Siedenburg & McAdams | High for the distinction; mapping to hard techno inferred |
| 5 | Sidechain-shaped envelope (ducking depth, release) | Envelope reshaped by kick-triggered compression | Rumble (heavily ducked, P-centre delayed) vs kick vs hats | Brøvig-Hanssen 2020; Attack Magazine; Perc | Moderate–high; unmeasured in hard techno |
| 6 | Crest factor (peak/RMS) | Transient-to-sustain ratio | Kick/clap/perc (high) vs rumble/pad (low) | Ziemer & Linke 2024 | Moderate; track-level only so far |
| 7 | Low-frequency energy / tilt below ~150 Hz | Sub weight | Rumble and kick body vs everything else | Attack Magazine; Garcia 2015 | Moderate; practitioner consensus, thin formal backing |
| 8 | Onset density / inter-onset interval | Events per beat or bar | Hats/offbeat perc (high) vs kick (low, regular) vs clap (fixed low) | Zehren 2024; Zeiner-Henriksen 2010 | High for the concept; no hard techno measurement |
| 9 | Syncopation index against the kick | Rhythmic conflict with the pulse | Pulse-carrying kick vs syncopated groove elements | Witek 2014 | High; not tested in 4-on-the-floor techno |
| 10 | Subdivision → perceived tempo (filled-duration) | Subdivided intervals feel slower/denser | Hats' contribution to "drive" independent of BPM | Repp 2008 | Low–moderate; inferential |
| 11 | Section-level energy, timbral and harmonic novelty | Composite role-handoff markers | Breakdown vs buildup vs drop | Zehren 2024; Yadati 2014; Kim 2024 | High — best validated in the sweep |
| 12 | Bar/phrase position (4/8/16/32) | Where in the hypermeter an event falls | When a role change is licensed | Butler 2006; Iler 2011 | Moderate; structural, not acoustic |
| 13 | Transition devices (riser trajectory, filter sweep, silence gap) | Swept broadband noise or a gap before a change | Transition role | Iler 2011; Solberg & Steinsvik 2015 (abstract only) | Moderate; not reduced to one feature |
| 14 | Phase coherence across the kick/rumble stack | Layers reinforce vs cancel | Foundation integrity | Perc (MusicRadar) | Low; single practitioner claim |

## Gaps

- No source studies post-2018 hard techno at the level of individual sound design. The only techno-specific MIR paper (Ziemer & Linke 2024) covers 1984–1994 at track level.
- The rumble has zero peer-reviewed acoustic literature. Everything is tier 4/5 tutorial plus one adjacent MTO paper on sidechain P-centre effects.
- No first-person written production statements from Nico Moreno, I Hate Models, 999999999 or SNTS were found above tier 6.
- No drum-classification dataset contains distorted, pitched hard-techno kicks or rumble layers, so published classification accuracies cannot be assumed to transfer.
- Hooks (stabs, leads, vocal chops) have essentially no dedicated structural-role literature.
- No study links hi-hat subdivision rate to perceived drive in 4/4 techno specifically.
- The Solberg & Steinsvik (2015) PDF could not be parsed; cited from its abstract.
- No literature quantifies distortion staging (stages, drive per stage) against perceived role, despite it being a constant theme in tutorials.
