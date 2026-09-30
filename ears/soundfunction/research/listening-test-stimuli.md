# Listening-test stimuli: from synthetic to real

## The problem

The listening test asks a producer which of two sounds is more of a clap, a
hat, a kick. Until now both sounds in every pair came from my own
synthesiser. Note one already recorded the flaw in passing: my claps rose in
48 ms where real claps rise in 3. What was missing was a number for how
general that failure was.

`listen/realism_check.py` supplies it. Every stimulus is measured and compared
against the distribution of 318 real one-shots of the same job, using the
freely licensed library in `library/real/`. A stimulus counts as out of range
on a feature when it sits outside the p10-p90 band of real sounds doing that
job.

The synthetic set: **139 of 348 feature checks out of range, 40%**. Attack
time, the single cue a listener keys on hardest, was out of range on 38 of 58
stimuli. A producer answering those questions was judging sounds that are not
the thing they are called, so the answers could not validate the measures
they were meant to validate.

## What replaced it

`listen/real_sweeps.py` builds each stimulus from a real one-shot instead.
For each job it picks the most ORDINARY real sound available, the one nearest
the median of its job in z-scored feature space, on the grounds that an
oddity makes a bad base for a controlled comparison. Then it moves exactly one
thing: tail length, brightness, drive, or pitch. The timbre stays real and the
pair still isolates a single variable, which is what the old sweeps were for.

The result: **42 of 276 feature checks out of range, 15%**. Attack time out of
range on 7 of 46 rather than 38 of 58.

| | synthetic | real-source |
|---|---:|---:|
| stimuli | 58 | 46 |
| out of range | 40% | 15% |
| attack time out of range | 38/58 | 7/46 |
| decay out of range | 20/58 | 7/46 |
| crest out of range | 24/58 | 5/46 |

## Licensing

Sources are the archive.org packs in `library/real/sources.md`, chosen
originally because they are CC BY, CC0 or Public Domain Mark and can therefore
be redistributed. Credit lines travel with each stimulus into `pairs.json` and
the survey page renders them from that data, which is what CC BY requires.

Corpus audio is never used for stimuli. Those tracks are mostly ND-licensed,
so neither they nor anything separated out of them may be republished.

## Answers stay separable

Every pair now carries a `set` field, and the client submits it with each
answer. Answers collected against the synthetic stimuli record as `v1-synth`,
the new ones as `v2-real`. Three answers exist from the synthetic set, from
one producer of fifteen years, on 8 September 2026. They are kept, and marked,
rather than silently pooled with answers to a different question.

## The better version of this, still to come

These stimuli are real drum machines and samplers, not hard techno. The genre
ideal is Anthony's own racks rendered as one-shots, which he owns and may
publish. That job is specified in `research/live-oneshot-pack.md` and runs on
the machine where Live lives. When that pack exists, run `realism_check.py`
against it: it should score better than 15%, and if it does not, the reason
will be worth knowing.
