# zpkt

A techno production system built as one body. Four parts form the spine,
and the spine runs across every stage of making a track.

| Part | Job | Question it answers |
|---|---|---|
| [`ears/`](ears/) | Measure | What does it sound like, objectively? |
| [`hands/`](hands/) | Act | How does intent become a change in Live? |
| [`taste/`](taste/) | Prefer | Which version would Anthony pick? |
| [`engineer/`](engineer/) | Decide | What should be tried next, unattended? |

Beside the spine:

- [`humming/`](humming/) turns a hummed idea into production data (notes,
  tempo, key). It is its own product and feeds `hands`.
- [`lib/`](lib/) is shared infrastructure, first class in the design:
  - [`lib/rig/`](lib/rig/): the Live runtime — headless display, startup,
    preflight.
  - [`lib/record/`](lib/record/): what the system keeps — models, renders,
    publishing to [anthonybecker.me/skrng](https://anthonybecker.me/skrng/).
  - [`lib/contracts/`](lib/contracts/): the JSON that crosses between parts.

## The spine is perpendicular to the lifecycle

Every stage of a track uses all four parts. Mastering is a stage, not a
component.

| Stage | ears | hands | taste | engineer |
|---|---|---|---|---|
| Sketch | pitch, tempo, key | hum → MIDI, macros | which idea to keep | — |
| Sound design | knob-sweep measures | set knobs, knob maps | which kick | search over settings |
| Arrange | section energy | Delete Time, move clips | which cut | cut candidates |
| Mix | corpus distance, pump | bus settings | which balance | overnight loop |
| Master | loudness, true peak (`mlab`) | limiter, render | ABX picks | hypothesis runs |
| Deliver | codec checks | render, upload | — | — |

Two rules keep the parts honest:

- **Objective judgment is `ears`.** Anything measurable — loudness,
  distance to the 508-track reference corpus — is a measurement.
- **`taste` only models preferences.** It learns from Anthony's picks, which
  are scarce, so the engineer should meet objective targets first and ask
  him only to choose between versions that already pass.

## What lives where

| Directory | From | Notes |
|---|---|---|
| `hands/` | github.com/becker929/hands | Live control, recorder, vibe server |
| `hands/sweeps/` | untracked hands folder, Sep 2026 | knob-to-measure sweep harness and results |
| `hands/skills/` | the old Mac's agent skills | driving Live: OSC + LOM, virtual display, export |
| `hands/macros/hammerspoon/` | github.com/becker929/hammerspoon-config | music-desk macros, render + upload, backups |
| `ears/` | github.com/becker929/ears | `ears analyze` — the AudioProfile |
| `ears/mlab/` | the HW002 mastering lab | calibrated meters, 81 known-answer tests |
| `ears/soundfunction/` | anthonybecker.me research branch | sound-function measures, knob-map results, docs |
| `taste/` | github.com/becker929/taste (+ taste2 prototype) | preference judge, pick corpus |
| `engineer/` | taste's loop, the lab's hypothesis runner, autodaw's GA | `engineer loop`, `engineer hyp run` |
| `humming/` | anthonybecker.me research copy | transcriber and HumTrans benchmarks |

Every import kept its git history (`git log -- <path>` goes back to 2025).
Audio, models and databases were stripped from history and stay out of git.
The design and history are written up as notes 15–19 on
[anthonybecker.me](https://anthonybecker.me/notes/three-eras/).

## Quick start

```bash
lib/rig/start_headless.sh                 # bring up Live on the virtual display, check the audio clock
eval "$(lib/record/fetch_models.sh | grep ^export)"   # embedding model for ears
cd ears && uv run ears analyze take.wav    # measure a render
cd hands && uv run hands record --arrangement --beats 80 --output take.wav
cd engineer && uv run engineer hyp run hypotheses/H001-loudness-buys-nothing-on-youtube.yaml
```

Each part is its own uv project. Run a part's tests from its directory:

```bash
cd hands && uv run pytest
```

CI runs every part's tests on each push, including contract tests that fail
if a part's output drifts from `lib/contracts/`.

## Working rules

- Work on copies of Live projects, never the originals.
- Trust the rendered file, not a report: measure its peak.
- Calibrate a measure against a known answer before using it.
- Commit working code the same day. Untracked work gets left behind.
- Keep audio, models and data out of git (see `.gitignore`).
- The vibe server is local-only; its code-changing endpoints need `VIBE_TOKEN`.
