# Estimator inventory for the asking transcriber

Draft of 24 September 2026. Follows the design note
[A humming transcriber that asks instead of listening harder](https://anthonybecker.me/notes/asking-not-listening/).

Every quantity the harness estimates is one row below. For each:

- **Evidence**: the channels that carry it (the design wants two per fact).
- **Candidates**: estimators worth running, strongest first, with what is
  measured here (on HumTrans, marked **HT**) or published (marked with the
  source; **PR** peer reviewed, **PP** preprint). Nothing is picked for being
  cheap. Picks are provisional until Anthony's own takes are in.
- **Doubt**: the number that triggers a question, and whether it is known to
  track errors.
- **Where**: **S** = the cloud sandbox (4 CPU cores, 15 GB, no GPU; good for
  batch benchmarks on HumTrans). **M** = the Mac mini (Apple silicon, 16 GB
  unified memory; the live app, the microphone, MPS/MLX/Core ML). Everything
  below fits in 16 GB at once: the largest models are 50-90 M parameters.
- **Decides it**: the test that settles the choice.

Source notes: `research/sound-function/repo/humtrans/*.py` produced every
**HT** number; the literature survey behind the rest is summarised at the end.

HumTrans caveat: it is closed-mouth humming sung along to MIDI. Its note
starts are much harder than "dum" starts, its labels are the score played to
the hummer, and its timing includes each hummer's delay. So HT numbers rank
estimators; they do not predict accuracy on Anthony's "dum" takes.

---

## 1. Timing reference

### 1.1 System latency (speaker to microphone)
- **Evidence**: the click, played by the app through the speaker and heard by
  the microphone. The app knows when it sent each click.
- **Candidates**: cross-correlate the recorded high band with the click
  template; fit a straight line through click times (done in
  `transcriber/pilot.py`: 0.8-1.0 ms residual on synthetic takes).
- **Doubt**: line-fit residual. Above ~3 ms means a missed or extra click.
- **Where**: M (needs the app's send times); S can check recorded files.
- **Decides it**: loopback test once per device and session. No learning.

### 1.2 Singer asynchrony (when a sung note lands against the beat)
- **Evidence**: note start against the click grid.
- **Which instant counts**: the "d" burst or the vowel onset. The perceptual
  centre of a sung syllable sits near the vowel, and people lead a metronome
  by tens of ms (Repp and Su 2013, PR). Measure both; keep the per-user
  offset between them (`pilot.py` already measures the consonant-to-voicing
  lead per take).
- **Candidates**: a per-user distribution (mean, spread), by tempo, and by
  warm-up state. Not a constant.
- **Doubt**: spread of the distribution; a note far outside it is asked about
  ("early on purpose?").
- **Where**: M collects; S or M fits.
- **Decides it**: calibration takes over the three songs at several tempi.
- **Known**: HumTrans hummers trail sung-along MIDI by 60-270 ms per person
  (two by ~850 ms), steady within a take (HT). That was sing-along; ours is
  call-and-response to a click, expected to be tens of ms.

---

## 2. Pitch

### 2.1 Frame pitch (f0)
- **Evidence**: the voice itself; the drone is a known reference in the same
  recording.
- **Candidates** (published, lars76/pitch-benchmark v2, repo, maintained by
  SwiftF0's author; overall F1 over 10 corpora and 8 degradations):
  SwiftF0 0.778, RMVPE 0.768 (best on solo singing, Vocadito 0.862),
  FCPE 0.728, CREPE 0.69, PESTO 0.68, pYIN 0.51. pYIN has the fewest false
  voicings, useful in an ensemble. HT benchmark on 150 test recordings:
  **pending** (`humtrans/pitchbench.py`: note accuracy, voicing, jumps,
  confidence AUROC, speed).
- **Doubt**: every tracker gives a per-frame confidence; none is calibrated.
  Trackers also carry fixed cent biases of 10-40 cents (Koguchi and Koriyama
  2026, PP), the same size as the tuning we want to measure.
- **Where**: all run on S and M. SwiftF0 is ONNX on CPU (~400x real time);
  RMVPE and FCPE run on MPS, with community MLX ports of RMVPE.
- **Decides it**: HT ranking, then bias against the drone in Anthony's takes.
  Provisional: SwiftF0 + RMVPE, with pYIN for voicing, each bias-corrected on
  the drone.

### 2.2 Tuning offset and drift
- **Evidence**: circular mean of note deviations from the semitone grid;
  the drone's recorded pitch.
- **Candidates**: drone-referenced offset per take; a slow random walk for
  drift within a take (the query-by-humming literature finds local errors far
  more common than cumulative drift: Meek and Birmingham 2004, PR).
- **Known**: HumTrans hummers median 5 cents flat; one 36 cents flat; held
  notes a median 18 cents off their semitone (HT). Synthetic takes: `pilot.py`
  reads a 15-cent-flat voice as 9-14 flat.
- **Doubt**: spread of note deviations; a note near a semitone boundary
  (40-60 cents off) is a pitch question.
- **Where**: S or M.
- **Decides it**: calibration takes with the drone, against the drone.

### 2.3 Note pitch (the semitone)
- **Evidence**: frame pitch over the note's middle; the key; the contour
  swipe; playback judgement.
- **Candidates**: median f0 over the middle half, tuning removed (what HT
  used); a posterior over semitones from the tracker's pitch distribution
  times a key prior and a melody prior; ROSVOT's note pitch as a vote.
- **Known**: once timing is fixed, 20-30% of well-timed notes get the wrong
  semitone from the published models, leaning flat by one semitone (HT).
- **Doubt**: posterior margin between the top two semitones.
- **Decides it**: accuracy against confirmed notes from Anthony's sessions.

### 2.4 Octave (register)
- Not a melody fact: two in five HumTrans takes sit an octave from their
  label (HT). Ask once at export which register to write in; never score it.

---

## 3. Notes

### 3.1 Note starts
- **Evidence**: the consonant; the click grid; a tap; rhythm syllables.
- **Candidates**, HT (150 test recordings, 50 ms / 100 ms tolerance, each
  recording's delay removed, closed-mouth humming):
  MIR-ST500 singing model 76 / 90, madmom CNN 68 / 78, madmom RNN 65 / 79,
  pYIN pitch changes 55 / 73, SuperFlux 51 / 82, spectral flux 46 / 79.
  Published on untrained singers (ISMIR2014 set, 50 ms): phoneme-informed
  model (Yong, Su and Nam 2023, PR) 93.1; MusicYOLO 94.2; Tony 66. The
  phoneme-informed model helps most with re-onsets on the same pitch, which
  is the "dum dum dum" case.
- **Click contamination**: a recorded click masks the consonant. `pilot.py`
  drops starts within 15 ms of a click and restores them from the voicing
  onset minus the take's consonant lead; on synthetic takes it recovers 50-51
  of 51 notes.
- **Doubt**: detector activation height; disagreement between the consonant
  detector and the pitch track.
- **Where**: madmom and the pitch-based rule run anywhere; the MIR-ST500 and
  phoneme-informed models are small and run on M (MPS).
- **Decides it**: Anthony's "dum" takes, where each start is confirmed.
  Provisional: madmom CNN on the consonant, pitch-track voicing as the second
  source.
- **Licence**: madmom's model weights are CC BY-NC-SA (fine for personal use).

### 3.2 Note count and segmentation
- **Evidence**: the new-consonant rule; rhythm syllables; the pitch track.
- **Candidates**: ROSVOT (ACL 2024, PR; MIT; 12 M parameters; COnPOff 77.4
  in domain, 30-47 out of domain) as a note-level vote, run on HT now
  (**pending**); GAME (OpenVPI 2026, MIT; successor to SOME) whose diffusion
  boundary sampler gives several segmentations, a direct source of doubt, and
  which re-estimates pitch for user-moved boundaries. GAME's weights are on
  GitHub releases, reachable from M, not from S.
- **Doubt**: disagreement between the consonant count and the syllable count;
  spread of GAME's sampled segmentations.
- **Decides it**: count errors on confirmed takes.

### 3.3 Note length and value
- **Evidence**: rhythm syllables; the grid; closure on "duck".
- **Candidates**: with a click, snap to the grid with a per-user asynchrony
  model and a note-value prior (a hidden semi-Markov model over tatums, as in
  Nishikimi et al. 2021, PR: their language model mainly cuts onset and
  offset errors). The beat-conditioned quantiser of Wachter, Murgul and
  Heizmann (PP, 97.3% onset F1 on piano) is the only neural one built to use
  a metronome; weights not confirmed available.
- **Doubt**: posterior over note values at each note.
- **Decides it**: note-value accuracy on confirmed takes.

---

## 4. Time and structure

### 4.1 Tempo (free take)
- **Evidence**: note starts; the metronome check (half and double offered).
- **Candidates**, HT (1,534 takes, truth = label tempo):
  audio tempogram right 23%, double 35%, half 13%, other 23%; its confidence
  does track being right (AUROC 0.79). From note starts alone: right 18%.
  Beat This! (Foscarin et al. 2024, PR; MIT): **pending**
  (`humtrans/beats.py`). Symbolic: Cemgil and Kappen 2003 (PR) and metrical
  HMMs give a posterior over tempo octaves from the starts.
- **Reading**: the metrical level (which pulse is "the beat") is a notation
  choice, not in the audio. Asking half or double is the right design, not a
  fallback.
- **Where**: all on S and M.

### 4.2 Meter and downbeat
- **Evidence**: note starts and accents; the user's answer.
- **Candidates**: Beat This! downbeats (**pending** on HT); BeatNet's particle
  filter (PR, CC BY 4.0) for a posterior over meter; a metrical HMM on the
  starts.
- **Doubt**: posterior over 2, 3, 4 beats per bar.
- **Decides it**: HT meter accuracy (labels: mostly 4/4 and 2/4), then asking.

### 4.3 Key
- **Evidence**: the hummed notes; the drone the user accepts.
- **Candidates**, HT (1,182 takes whose label key fits their own notes):
  Temperley-Kostka-Payne profile on hummed notes 52% exact, 78% with relative
  major or minor; Krumhansl-Kessler 30% / 50%. Margin barely tracks being
  right (AUROC 0.60). Published: Temperley's Bayesian melody model 87.7% vs
  Krumhansl-Schmuckler 75.4% on folk melodies (Temperley 2008, PR), and it
  gives a posterior over 24 keys. Audio key models (S-KEY) are trained on
  mixes and do not fit solo humming.
- **Reading**: key doubt is badly calibrated, so confirm it by ear: the app
  proposes a drone, the user accepts or moves it.
- **Where**: S or M.

### 4.4 Phrase boundaries
- **Evidence**: breaths and silences; long notes; melodic closure.
- **Candidates**: silence gaps from the voicing track; MelodyT5 (ISMIR 2024,
  PR; MIT) has a segmentation task on symbolic melody.
- **Doubt**: gap length near the threshold; disagreement with melodic cues.

---

## 5. Priors and intent

### 5.1 Melody prior
- **Candidates**: IDyOM (variable-order Markov; tiny; trains on the user's
  own confirmed melodies); MelodyT5 (MIT); NotaGen small or medium (110 M /
  244 M, MIT); Anticipatory Music Transformer (Apache-2.0; infilling suits
  "fill the uncertain note"). Use for rescoring n-best transcriptions, with a
  weak weight so new melodies are not pulled toward clichés.
- **Where**: M (all fit in 16 GB); S for offline scoring.

### 5.2 Intent (does this sound right to you)
- **Evidence**: playback against the free take; spoken or typed feedback.
- **Estimator**: the user. The dialogue model (Claude, over the API) reads the
  feedback and picks the next question; it never estimates pitch. Audio
  language models are measurably poor at pitch, key and beat (CMI-Bench,
  ISMIR 2025, PR), so none is used as a source.

### 5.3 The ceiling: take-to-take agreement
- `pilot.py` scores every pair of click takes of a song against each other
  with the paper's note metric, keys and grids lined up. On synthetic takes
  with known jitter the pipeline reads 0.91-0.96 where perfect detection
  would give about 0.98. The design note predicts Anthony's real "dum" takes
  exceed 0.90.

---

## What runs where

| Component | Sandbox | Mac mini, 16 GB |
|---|---|---|
| Click capture, latency loopback | no | yes (the app) |
| SwiftF0, pYIN, madmom, SuperFlux | yes | yes |
| RMVPE (90 M), FCPE, PESTO | yes (CPU, slow for RMVPE) | yes (MPS; MLX port) |
| ROSVOT (12 M) | yes (patched for CPU; ~15 s a take on a busy machine) | yes (MPS) |
| GAME (~50 M) | no (weights not reachable) | yes (ONNX or MPS) |
| Beat This!, BeatNet | yes | yes |
| Temperley key, HSMM quantiser | yes | yes |
| MelodyT5, NotaGen-small, AMT | slow but possible | yes |
| Per-user calibration fits | yes | yes |
| Fine-tuning a 12-50 M note model on confirmed takes | too slow | feasible on MPS |
| Dialogue model | API | API |

## Open, and what settles it

1. Pitch tracker ranking on HT: `pitchbench.py` (running).
2. ROSVOT on HT with per-singer delay: does a modern robust note model beat
   MIR-ST500's 47? (running).
3. Beat This! tempo octave and meter on HT (running).
4. GAME on the Mac, same protocol.
5. Anthony's three songs through `pilot.py`: take-to-take agreement, the
   asynchrony distribution, the consonant lead, tuning, and which rows above
   actually need a learned model.
