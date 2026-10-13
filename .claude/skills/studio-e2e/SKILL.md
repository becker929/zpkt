---
name: studio-e2e
description: Test studio end to end as Anthony uses it - the real server, Kokoro and Parakeet, the real Claude session and narrator - with a virtual user on an iPhone-sized WebKit who talks to it, taps the cards and switches apps, then hold the run to fixed rules and write a report. Use after any change to studio (lib/harness/studio, lib/voice, the music skills), before saying a studio feature works, and to reproduce a problem Anthony reports from his phone.
---

# studio-e2e

```bash
cd lib/harness
uv run --extra dev python -m e2e                         # the whole scenario, ~10 min
uv run --extra dev python -m e2e --only slider,finer     # some parts (a part's prerequisites run first)
uv run --extra dev python -m e2e --keep-going            # carry on after a part fails
```

It runs from the checkout it is in. The Claude session works in that checkout and uses its skills, so a branch is
tested as it is. The studio's data goes in the run's folder (`~/_agent_scratch/e2e/runs/<time>/`). The running
`harness serve` and Anthony's chat are never touched.

**Live is not touched either.** Plans read Live's renders already in the cache (linked, read only) and render
anything new as stand-in tones at the kit's tempo (`HANDS_PLAN_RENDERER=fake`). `--live` renders new plans in Live:
use it only when Anthony is there, one supervised run at a time. Screenshots come from a stand-in screen; use
`--real-screen` for the Mac's own.

## What a run does

The parts (`e2e/scenario.py`), in order:

- **slider**: asks for a drive slider by voice, waits for the card, checks that the sweep and the card agree.
- **finer**: taps a stop, then Finer here, and checks the text and the new slider's range.
- **background**: switches apps while the mic listens, as iOS does it (hidden, capture tracks ended, audio
  interrupted), comes back (tapping if the page asks), and checks the next spoken line is heard.
- **intents**: "Loop that three times" plays without Claude.
- **keep**: taps a stop, then Keep.
- **typed**: a typed turn is answered out loud.
- **screens**: Claude's steps come with screenshots.

The virtual user speaks (Kokoro, voice am_michael, lines cached in `~/_agent_scratch/e2e/voices/`) only once the
page says it is listening. That is the moment Anthony would start talking, so a lost first word is a failure.

## The rules every run is held to (`e2e/checks.py`)

- Nothing plays while the mic is open (except the ready cue in its first 0.4 s).
- One sound at a time.
- Every render the Mac plays is introduced, with a count-in ("three, two, one").
- No narration once music is ready.
- Every line is heard from its first word.
- Every turn the Mac offered got the user's audio.
- There are no errors on the page or in the chat.

## Reading the report

`report.md` in the run folder opens with how many checks passed and a table of every check. Then come the evidence
for each failure, and a timeline on the page's clock: what the user did, what the Mac heard, said (with each
utterance's role) and played. `screens/` has a screenshot at each step and at any timeout. `heard-*.wav` is what
the speakers played. `wire.json` is the socket both ways, and `engine.json` is every item the page played.
`studio/studio.sqlite3` holds the chat and the turn timings.

The command exits 1 if any check failed. Say which checks failed and why, from the evidence and the timeline. A
failure in a part (a timeout) comes with a screenshot named `timeout-<what>` or `failed-<part>`.

Claude is real, so its words differ between runs, and so can its choices (a kit, a range). The checks are about
what the app does with them. If a part fails because Claude chose differently, read the timeline and say so, rather
than calling it an app failure.
