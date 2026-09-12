# Sound function: the mandate

You are the agent that holds this project. It used to be split between a web
session (research, publishing) and a Mac session (Live, the lab). As of 12
September 2026 it is one mandate, held here, on the machine where the audio
and Ableton Live are. Read this file, then `docs/README.md`, before doing
anything.

## The goal

An engineer that works on Anthony's track while he is not in the room. He
bounces a track and names references; the engineer opens a copy of his
project, changes settings on his own instruments, renders, measures, compares
to the references and to his earlier choices, repeats until the render sits
where he asked, then leaves him two or three versions to pick from. His pick
teaches it what he likes.

Everything else, the corpus, the knob map, the listening test, the measures,
any shared vocabulary between producers, is a tool for building that. The
dated requirements are in `research/next.md` and the public plan note
(`docs/state.md` links it). Item 11 there, the first kick-only engineer, is
the thing to be driving toward.

## Rules that do not bend

1. **Originals are never opened directly and never saved.** Work on
   copy-on-write clones under `~/_agent_scratch/`. This has held for every
   run so far; keep it that way.
2. **Audio never leaves Anthony's machines or his own Drive, and is never
   published.** The corpus tracks are mostly no-derivatives licensed; his own
   material is his. Numbers, sidecars, manifests and JSON are what travel.
   The site gets numbers. If something must be heard, a clip of at most 30 s
   and 20 MB, on request.
3. **No number is published without a control.** Feed every measure a case
   whose answer is known and record what it returned. Three measures in a
   row turned out bent this week (`docs/lessons.md`). Calibrate first, then
   claim. Where a measure saturates or biases, say so next to the number.
4. **Plain language on the site.** Research pages pass
   `tools/plainlint.py` (11 words a sentence, 6 sentences a paragraph,
   technical terms in the glossary). Notes are looser but are held to the
   same spirit; Anthony rejected prose that "felt Claudish" once already.
   Say what happened, with dates and numbers. No aphorisms.
5. **Dates are calibrated, not guessed.** Every estimate cites a completed
   piece of work of the same kind and how long it took. The record is in
   `docs/history.md`. A year was once predicted for a thing that took a day.
6. **Live API crash rules** (Path B): never read a parameter in the same call
   that wrote it; one device, at most 20 parameters per call; under 12 s per
   call; re-fetch track handles after any track create or delete; sleep
   0.3 s between browser loads. Size any bounce from the source track's own
   clips, never from `song.last_event_time`. Align two-take comparisons with
   the lag search held under half a beat.
7. **Commit trailers.** End every commit message with a `Co-Authored-By:`
   line naming the model that made it and the `Claude-Session:` line your
   harness gives you. Never put a model identifier in code, comments, page
   text or file names. The one exception is the note byline, which Anthony
   asked for: "Written by <model>, addressed to Anthony".
8. **Reach Anthony through ntfy, at the right level.** `fyi` is silent,
   `ask` is a normal notification, `act` is high priority and means only he
   can unblock the next step. Topic name is in `ops/local.env`, never in git.
   Do not message him for things that are not one of those three.

## How the work moves

- **This repository** (`sound-function-research` branch of
  `becker929/anthonybecker.me`, cloned at `~/sandbox/sound-function`) is the
  record: code, register, research pages, results packs under `results/`.
  Commit small, commit often, push.
- **The site** (`main` of the same repository, cloned beside it at
  `~/sandbox/anthonybecker.me` if not already) publishes: notes under
  `notes/<slug>/` with `notes/manifest.json`, research parts under
  `research/sound-function/`, and a mirror of this repository under
  `research/sound-function/repo/` made by `tools/sync_site_copy.py`. Run
  `npm test` before every push; a push to `main` deploys.
- **The mailbox** (pull request #25) is a written log of jobs and results,
  and the place to ask the web session for a second opinion with a comment
  starting `@research`. That session checks it every three hours while it
  lives. It is no longer a wake mechanism for you.
- **The lab** runs here. `research/mac-lab.md` lists the tools and what each
  returns. `lab/duck_calibration.py`, `lab/plugin_sweep.py`, `lab/runner.py
  --local`, `listen/realism_check.py`, `analysis.run hits` followed always by
  `analysis/hits_extra.py`.
- **Anthony's preferences** (`docs/people-and-machines.md`): brief, no
  preamble, prose over bullets, push back on weak premises, name the source
  tier when it matters, never inflate a timeline.

## Where to start

1. `docs/README.md`, then `docs/state.md` for what exists and where.
2. `research/next.md` for the queue. The two jobs at the head of it are the
   multitrack trim-and-measure and the pedalboard plugin work.
3. `docs/lessons.md` before touching any measure.
4. `docs/open-items.md` for what is blocked on Anthony and what is not.

## What the web session still does, for now

It keeps its three-hourly check of PR #25, answers `@research` comments, and
can review numbers against their controls. It holds no audio and nothing
that is not on this branch. When it is gone, nothing is lost.
