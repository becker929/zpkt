# 04 — Stage 3: sound segmentation

Split audio into spans and label each one speech, music, or other, so the
waveform view can colour-code them.

Anthony asked for two or three approaches to be built and compared, not for one
to be picked up front. This stage is a bakeoff. It ends with a report and a
recommendation, not with a single shipped classifier.

## Schema addition

```sql
CREATE TABLE span (
  id         INTEGER PRIMARY KEY,
  hash       TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  method     TEXT NOT NULL,   -- 'yamnet' | 'pyannote' | 'clap'
  start_s    REAL NOT NULL,
  end_s      REAL NOT NULL,
  label      TEXT NOT NULL,   -- 'speech' | 'music' | 'other'
  confidence REAL,
  detail     TEXT             -- finer label, e.g. 'drum kit', 'laughter'
);
CREATE INDEX idx_span_hash_method ON span(hash, method);
```

Storing `method` lets all three run over the same files and be compared directly
in the interface. That comparison is the deliverable.

## The three approaches

**YAMNet.** A pretrained tagger over 527 AudioSet classes. Runs on roughly
1-second frames, CPU-fast, no training. Map its classes down to the three
labels, keeping the original class in `detail`. This is the standard baseline
and the reference the other two are judged against.

**pyannote voice activity detection, plus a music detector.** Purpose-built for
speech boundaries, so it should win on precise speech timing. Needs a second
component for music, and a third label falls out as "neither". Requires a
Hugging Face token and accepting the model licence.

**CLAP zero-shot.** Reuse `laion/larger_clap_music`, already explored in
`clap-poc/`. Score each span against text prompts, so the taxonomy is editable
without retraining. This is the only approach that can label open-ended
"interesting sounds" by description. Slower per span and weaker at boundaries.

Copy any needed CLAP code into this project. Do not import across project
directories; that convention is in the repo's `CLAUDE.md`.

## Boundaries versus labels

These are two different problems and the approaches split on them.

YAMNet and CLAP classify fixed frames, so boundaries come from merging adjacent
frames that share a label. pyannote produces true boundaries directly. Judge
boundary quality separately from label quality, because a method can be good at
one and bad at the other.

Merge frames with a median filter over the label sequence, then drop spans
shorter than 0.5 seconds. Without this, frame-level noise produces hundreds of
unusable slivers per file.

## Evaluation

Hand-label a set of 40 to 60 files sampled across the collection's folders. The
collection is varied: `sounds - spoken` is mostly speech, `music - previous
demos` is mostly music, and `sounds - foley` is mostly neither. That spread is
the test set.

Report per approach: label accuracy, boundary error in seconds, runtime per
audio-minute, and peak memory. Then recommend one, with the reasoning written
out.

## Disk

Model weights run 100 MB to 1 GB each, and three approaches means three
downloads. The volume has 20 GB free. Resolve the `audio-library/` duplication
before starting this stage.

## Acceptance

- All three run over the evaluation set and write spans.
- The waveform view colour-codes spans and can switch between methods.
- The comparison report lands at `agent_notes/audio-browser/05-bakeoff-results.md`.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [03-server-and-ui.md](03-server-and-ui.md)
- **next**: [05-triage.md](05-triage.md)
