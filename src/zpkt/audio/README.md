# zpkt.audio: measure a render

`zpkt.audio` (until 24 Nov 2026 the `ears` package; `ears` still works as a command and an import) takes an audio file and says what is in it, as numbers. It is what an agent uses instead of
listening, and what I use to check that a render is what I think it is.

It has two layers. The core is a set of calibrated meters (`zpkt.audio.meters`): loudness, true peak,
dynamics, spectra, a mix against references, EQ fitting. Each one is checked against a signal whose
answer is known before it is trusted. Around it sits a profile of a file (`ears analyze`) with an
embedding, and your own corpus of reference tracks to place a render in.

The meters were their own project, `mlab`, until 24 November 2026. The `mlab` command and
`import mlab` still work and reach the same code. Old names and new: `ears.X` is `zpkt.audio.X`,
`ears.meters.X` and `mlab.X` are `zpkt.audio.meters.X`; `ears ...` is `zpkt audio ...`.

## Run it

From the repo root (zpkt is one uv project; the audio half is its `audio` extra):

```bash
uv sync --extra audio
uv run ears measure take.wav                 # the full measurement sheet (calibrated)
uv run ears target mix.wav --refs refs.json --set hw002   # a mix against references, build and drop
uv run ears analyze take.wav                 # the profile: loudness, band shares, spectra, embedding
uv run ears corpus build ~/Music/references  # measure your reference tracks once
uv run ears corpus distance take.wav         # where a render sits among them
uv run ears --help                           # every command
```

`ears` and `zpkt audio` are the same command. `ears COMMAND` runs every meter command; `mlab COMMAND`
and `python -m mlab COMMAND` run the same meter commands with the same flags. The mastering lab's
guides, hypotheses, reports and calibration live in [`ears/mlab/`](../../../ears/mlab/): start at
[`ears/mlab/INDEX.md`](../../../ears/mlab/INDEX.md). Run lab commands from that folder; uv finds the
project at the repo root.

## Which numbers to trust for what

Two tools here measure loudness and spectra, and they do not agree to the decimal. They answer
different questions.

| Question | Use | Why |
|---|---|---|
| How loud, how hot, how limited (LUFS, LRA, true peak, PLR) | `ears measure`, `ears deliver` | Calibrated: EBU 3341/3342 and BS.1770 cases, cross-checked with pyloudnorm and ffmpeg. True peak is 8x oversampled. |
| Where a mix sits against references, per section | `ears target`, `ears refs --peaks` | Calibrated windows and band integration; dB relative to each window's own LUFS. |
| Which EQ moves bring stems to the references | `ears eqfit` | Recovers known moves on synthetic stems; reports its own model error. |
| Premaster faults, word length, dither, DC | `ears premaster`, `ears bitdepth` | Planted-fault and analytic checks. |
| What a render is like, and how close to my corpus | `ears analyze`, `ears corpus distance` | A profile, not a meter: pyloudnorm loudness, 4x true peak, five coarse band shares, librosa spectra and an embedding. Good for ranking renders, not for mastering decisions. |

For an agent that must not load audio into its conversation, [`brief.py`](brief.py) gives a short sheet of a
window of a file: `brief(path, start_s, end_s)` (LUFS, true peak, peak, RMS, crest, five bands as parts of the RMS:
sub under 60 Hz, low to 250, mid to 2000, high to 6000, air above; stereo correlation and width),
`spectrum` (third octaves), `over_time(path, step_s)` (RMS and peak per step) and `difference(a, b)`. It is a
quick reading, not one of the calibrated meters: the app's `render.bounce` and `render.measure` answer with it.

`uv run ears calibrate` runs every known-answer check and writes
[`ears/mlab/calibration/CALIBRATION.md`](../../../ears/mlab/calibration/CALIBRATION.md).

Bands differ between the two on purpose. The meters' band tables are all in
[`meters/bands.py`](meters/bands.py), with a table of which meter uses which. The profile's five
shares are in [`loudness.py`](loudness.py); its "sub" is 20-150 Hz, the meters' is 20-60 Hz.

## References and windows

A reference is a finished track you compare against. The meters read references in two forms, both
in [`meters/references.py`](meters/references.py): a `refs.json` (`id`, `file`, `drop`,
`barSeconds`, optional `set`), or a folder of audio files. `target` and `eqfit` measure a build
window (16 bars before the drop) and a drop window (16 bars from it), placed in seconds from each
file's own drop; [`meters/windows.py`](meters/windows.py) holds that layout and its HW002
defaults (drop at 24 s, bar 1.5 s).

## Your reference corpus

A corpus is a folder of tracks you want yours to sit among. No audio or measurements ship with
ears; you bring the folder.

```bash
uv run ears corpus build ~/Music/references           # writes ~/.cache/zpkt/corpus.json
uv run ears corpus distance take.wav
```

```
take.wav against 4 corpus tracks
 Measure                   Yours    Median       p10       p90     z
 lufs_integrated           -14.1     -6.04     -7.13     -4.64  -7.0
 true_peak_db             0.0644    -0.303    -0.805    -0.161  +1.5
 band_sub                  0.828     0.785     0.706     0.892  +0.4
 band_mid                 0.0507    0.0866      0.06     0.101  -1.5
 ...
Embedding: 0.963 to the corpus centre (corpus tracks: median 0.959, 10th percentile 0.954)
  0.958  Remon Verhoeve - Patriotic.wav
```

Each row is one measure: your render, the corpus median, its 10th and 90th percentiles, and `z`,
the number of corpus standard deviations from the corpus mean. Rows outside the 10th to 90th
percentile are highlighted. The embedding lines say how close the render is to the centre of the
corpus compared with the corpus's own tracks, and name the nearest ones.

`--out` and `--corpus` choose another file; `EARS_CORPUS` sets the default. Use several corpora
for several targets (a genre, a label, your own releases). With four tracks the percentiles mean
little; a few dozen is where the ranges start to say something.

## The embedding model

Embeddings use DCLAP from
[AudioMuse-AI-DCLAP](https://github.com/NeptuneHub/AudioMuse-AI-DCLAP) (AGPL-3.0), a distilled
CLAP. It is 22 MB and is not in this repo.

```bash
ears/scripts/fetch_model.sh  # downloads to ~/.cache/zpkt/models/dclap and checks the hashes
```

ears looks there by default; `EARS_DCLAP_MODEL` points it at another copy. Everything except
embeddings works without the model. Beat tracking (`--rhythm`) and pitch (`--pitch`) need madmom and
basic-pitch, which ears does not install: `uv pip install madmom basic-pitch` if you want them.

## Layout

| Path | What |
|---|---|
| `src/zpkt/audio/meters/` | The calibrated meters, one module per job: `loudness`, `dynamics`, `spectrum`, `bitdepth`, `sections`, `target`, `eqfit`, `premaster`, `delivery`, `compare`, `measure` (the sheet), `hypothesis`, `als`, `dsp` and `siggen` (reference processors and test signals). `bands`, `references`, `windows` hold those definitions once; `printouts` formats the long reports; `cli` is the `mlab` command. |
| `src/zpkt/audio/` | The profile (`analyzer`, `features`, `loudness`, `embeddings`, `rhythm`, `pitch`, `models`), the corpus (`corpus`), pairwise comparison (`similarity`) and the `ears` command (`cli`). |
| `src/ears/`, `src/mlab/` | The old names: `ears.X` is `zpkt.audio.X` and `mlab.X` is `zpkt.audio.meters.X`, the same modules (`zpkt._aliases`). |
| `ears/mlab/` | The mastering lab's files: guides, hypotheses, reports, spikes, calibration. |
| `ears/scripts/` | `fetch_model.sh`; `gen_schema.py` writes `lib/contracts/audio-profile.schema.json` from `models.py`. |

zpkt.audio imports nothing from zpkt.live. zpkt.live runs the meters in a subprocess
(`zpkt live library inventory --measure`).

## Tests

```bash
uv run --all-extras pytest -p no:cacheprovider tests/audio ears/mlab/calibration   # offline: no audio files, no model, no network
uv run --all-extras mypy              # strict for zpkt.audio (the root pyproject.toml)
GOLDEN_EXACT=1 uv run --all-extras pytest -p no:cacheprovider tests/audio   # every pinned number, bit for bit
```

Signals are synthesised. `ears/mlab/calibration/` holds the known-answer checks: each meter against a
standard's test case, a closed-form answer or an independent implementation. `tests/audio/golden/` pins
what every meter and command reports today, so a refactor cannot move a number unnoticed. A golden
that stops matching is a change in what ears reports: say so, do not rewrite the file. The contract
test fails if `lib/contracts/audio-profile.schema.json` is stale.
