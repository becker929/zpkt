# 06 — Stage 3 bakeoff results

Three classifiers were built and run over every sound the triage kept. This
records what they found, where they disagree, what they cost, and which one
should be the default.

All three runs finished. 19,407 spans over 942 sounds.

## The recommendation

**Default to `yamnet`. Use `vad` for speech boundaries. Do not default to
`clap`.**

The reasoning is agreement between unrelated models, because there is no
hand-labelled ground truth to score against.

| Pair | Agreement, time-weighted | Averaged per sound |
|---|---|---|
| `vad` vs `yamnet` | **82.9%** | 79.2% |
| `clap` vs `yamnet` | 60.6% | 61.4% |
| `clap` vs `vad` | 58.6% | 59.9% |

`yamnet` and `vad` share AudioSet's vocabulary but share no architecture, so
their 82.9% is two independent witnesses reaching the same conclusion. `clap`
agrees with neither much better than a skewed coin.

The label shares say the same thing:

| Method | other | music | speech |
|---|---|---|---|
| `yamnet` | 52.8% | 32.5% | 14.7% |
| `vad` | 57.6% | 32.6% | 9.7% |
| `clap` | 22.5% | **63.2%** | 14.4% |

`yamnet` and `vad` land within 0.1 points of each other on music. `clap` calls
nearly twice as much of the collection music as either. For a library being
triaged for non-metric sound — texture, noise, found recordings — a classifier
that hears most of it as music is worse than useless; it would hide exactly what
is being looked for.

### Cost

| Method | Wall | Per audio-minute | Realtime | Peak RSS |
|---|---|---|---|---|
| `yamnet` | 9.8 min | 0.21 s | **282×** | 682 MiB |
| `vad` | 85.7 min | 1.87 s | 32× | 903 MiB |
| `clap` | 97.6 min | 2.13 s | 28× | 391 MiB |

`yamnet` is roughly ten times faster than either alternative and runs on CPU,
leaving the GPU free. Whatever becomes the default runs over every sound ever
added, so this gap compounds.

### Where the split matters

`yamnet` reports 14.7% speech, `vad` 9.7%. That difference is where `vad` should
win: its speech comes from a boundary detector rather than frame votes, so its
edges are sharper and its false positives fewer. The sensible arrangement is
`yamnet` for the music-or-other timeline and `vad` stamped over it for speech,
which is already how `vad`'s own spans are constructed.

`clap`'s remaining value is not classification. It is the only one of the three
that can answer a written description, so it belongs behind a search box, not in
the default pipeline.

## What was run, and over what

The collection was queried, not assumed. At the time the runs started it held
**942 sounds, 45.8 hours**, counting only sounds that still have a file on disk
and are not in `soft_delete`. The brief quoted 956 sounds and 46.3 hours; the
triage kept going while this was being built, so 14 more sounds were discarded
in between. Discarded sounds were skipped entirely, as instructed.

One recording dominates the run. `compost/rejects/2019_10_23_06_33_02.mp3` is
11 hours 55 minutes long, 26% of the whole collection's duration on its own. The
three next longest add another 5 hours. Any timing here is really a statement
about those four files plus 938 short ones.

## The three approaches

| Method | What it is | Frame | Device |
|---|---|---|---|
| `yamnet` | YAMNet over AudioSet's 521 classes | 0.48 s | CPU |
| `vad` | Silero VAD for speech, AST for music | true boundaries for speech, 5.12 s for music | Apple GPU |
| `clap` | CLAP scored against 12 written descriptions | 2.5 s | Apple GPU |

Two of the three are not quite what the plan named. Both substitutions were
forced, and both were measured rather than assumed.

### pyannote is gated, so Silero VAD stands in

`pyannote/segmentation-3.0` needs a Hugging Face account, an accepted licence
and a token. An anonymous request for its `config.yaml` answers **401**. There is
no token anywhere on this machine and one cannot be created without the account
holder. So the approach was not skipped; the component was replaced.

**Silero VAD** fills the same role. It is a small recurrent detector built for
one job, it emits true speech boundaries rather than frame votes — which is the
property the approach was in the bakeoff for — it is MIT licensed, and it ships
its weights inside its wheel, so it downloads nothing at all.

Its music half is the **Audio Spectrogram Transformer** fine-tuned on AudioSet
(`MIT/ast-finetuned-audioset-10-10-0.4593`). It shares AudioSet's vocabulary
with YAMNet and shares none of its architecture, which is what makes comparing
them worth anything: where these two agree, two unrelated models agree.

To put pyannote back, write a class with the same two methods —
`speech_regions` and `music_frames` — and nothing above
`src/audio_browser/segment/vad.py` needs to change.

### `larger_clap_music` does not work, so `larger_clap_general` stands in

The plan named `laion/larger_clap_music`, the checkpoint explored in
`clap-poc/`. It is not usable for this task. On five files from this collection —
two spoken, two music renders, one foley recording — every cosine similarity it
produces sits between 0.002 and 0.009, and the ranking of the prompts comes out
**identical for all five files**. A voice memo and a finished music render are
the same sound to it.

The same five files through `laion/larger_clap_general` spread from about -0.21
to +0.21 and put "the sound of music" first for both music renders.

`larger_clap_music` is a music-only fine-tune. Its audio tower still separates
these recordings from one another; its text tower has collapsed for
general-purpose sentences, and zero-shot classification needs both towers.

One more thing had to be overridden. CLAP normally carries a trained
`logit_scale` for its softmax. In these converted checkpoints it comes out at
about 1.03 rather than the usual double figures, which flattens every
distribution to uniform no matter what the audio holds. The temperature is set
explicitly in `clap.py` instead, at 0.05.

## How frames become spans

All of the merging logic is in `src/audio_browser/segment/spans.py`. It loads no
model, opens no file and touches no database, which is why it carries 45 tests
of its own.

1. **Smooth.** A categorical median filter over a five-frame window. Ties keep
   the frame's own label, so smoothing never invents a label the frame did not
   already have.
2. **Merge.** Runs of frames sharing a label become one span. Confidence is the
   mean of the frames. `detail` is their commonest fine-grained class, which is
   how a stretch of music says "Drum kit" rather than only "music".
3. **Absorb, not drop.** The plan said to drop spans under 0.5 seconds. They are
   folded into their longer neighbour instead. Dropping would leave holes in the
   timeline, and a waveform with untinted gaps in it is harder to read than one
   with slightly wrong edges. The floor holds: the shortest span anywhere in the
   `yamnet` output is 0.96 seconds and not one is under 0.5.

`vad` is the exception to step 1 and 2. Its speech comes from a boundary
detector, so its spans are built the other way round: AST lays down a coarse
music-or-not timeline, and the VAD's speech regions are stamped into it at their
own, sharper, edges.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [05-triage.md](05-triage.md)
- **next**: none.
