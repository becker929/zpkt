# zpkt

A techno production system built as one body. The main path is three
parts, and it runs across every stage of making a track.

| Part | Job | Question it answers |
|---|---|---|
| [`ears/`](ears/) | Measure | What does it sound like, objectively? |
| [`hands/`](hands/) | Act | How does intent become a change in Live? |
| [`lib/`](lib/) | Support | What do the parts run on, keep and exchange? |

`lib/` is shared infrastructure, first class in the design:

- [`lib/rig/`](lib/rig/): the Live runtime — headless display, startup,
  preflight.
- [`lib/record/`](lib/record/): what the system keeps — models, renders,
  publishing to [anthonybecker.me/skrng](https://anthonybecker.me/skrng/).
- [`lib/contracts/`](lib/contracts/): the JSON that crosses between parts.
- [`lib/harness/`](lib/harness/): Claude Code jobs started from the
  browser (/skrng feedback), over an outbound socket to the site.

Beside the main path:

- [`humming/`](humming/) turns a hummed idea into production data (notes,
  tempo, key). It is its own product and feeds `hands`.
- [`prototypes/`](prototypes/) holds experiments not yet on the release
  path:
  - [`audio-browser/`](prototypes/audio-browser/): listen through a sound
    library once and decide what each sound is for; a collage editor beside
    it.
  - [`taste/`](prototypes/taste/): which version would Anthony pick? Its
    corpus holds five seed verdicts and no real picks yet.
  - [`engineer/`](prototypes/engineer/): what should be tried next,
    unattended? Its loop and genetic algorithm are not wired in.
  - [`letta-vibe/`](prototypes/letta-vibe/): a Letta agent that drives
    Live, a phone page for listening and feedback, and their MCP bridge.

## The main path is perpendicular to the lifecycle

Every stage of a track uses ears and hands. The prototype columns show
where taste and engineer would join. Mastering is a stage, not a component.

| Stage | ears | hands | taste (prototype) | engineer (prototype) |
|---|---|---|---|---|
| Sketch | pitch, tempo, key | hum → MIDI, macros | which idea to keep | — |
| Sound design | knob-sweep measures | set knobs, knob maps | which kick | search over settings |
| Arrange | section energy | Delete Time, move clips | which cut | cut candidates |
| Mix | corpus distance, pump | bus settings | which balance | overnight loop |
| Master | loudness, true peak, hypothesis runs (`mlab`) | limiter, render | ABX picks | — |
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
| `hands/` | github.com/becker929/hands | Live control: the `hands` library and CLI |
| `hands/sweeps/` | untracked hands folder, Sep 2026 | knob-to-measure sweep harness and results |
| `hands/skills/` | the old Mac's agent skills | driving Live: OSC + LOM, virtual display, export |
| `hands/macros/hammerspoon/` | github.com/becker929/hammerspoon-config | music-desk macros, render + upload, backups |
| `ears/` | github.com/becker929/ears | `ears analyze` — the AudioProfile |
| `ears/mlab/` | the HW002 mastering lab | calibrated meters, 81 known-answer tests, hypothesis runner (`mlab hyp run`) |
| `ears/soundfunction/` | anthonybecker.me research branch | sound-function measures, knob-map results, docs |
| `humming/` | anthonybecker.me research copy | transcriber and HumTrans benchmarks |
| `prototypes/audio-browser/` | autodaw `feature/audio-browser` | sound-library triage and collage |
| `prototypes/taste/` | github.com/becker929/taste (+ taste2 prototype) | preference judge, pick corpus |
| `prototypes/engineer/` | taste's loop, autodaw's GA | `engineer loop` |
| `prototypes/letta-vibe/` | hands' vibe server, frontend and MCP bridge | `letta-vibe vibe` |

The source repos (hands, ears, taste, taste2-prototype, autodaw,
hammerspoon-config) are archived, each with a README pointing here.

Every import kept its git history (`git log --follow -- <file>` goes back to
2025, across later moves).
Audio, models and databases were stripped from history and stay out of git.
The design and history are written up as notes 15–19 on
[anthonybecker.me](https://anthonybecker.me/notes/three-eras/).

## Quick start

```bash
lib/rig/start_headless.sh                 # bring up Live on the virtual display, check the audio clock
eval "$(lib/record/fetch_models.sh | grep ^export)"   # embedding model for ears
cd ears && uv run ears analyze take.wav    # measure a render
cd hands && uv run hands record --arrangement --beats 80 --output take.wav
cd ears/mlab && uv run mlab hyp run hypotheses/H001-loudness-buys-nothing-on-youtube.yaml
```

Each part is its own uv project. Run a part's tests from its directory:

```bash
cd hands && uv run pytest
```

CI runs every part's tests on each push, including contract tests that fail
if a part's output drifts from `lib/contracts/`.

## Security

Every service listens on loopback only and needs a secret; agents acting on
outside input run with least privilege. See [SECURITY.md](SECURITY.md) for
the services, their guards and the tokens to set (`MCP_BRIDGE_TOKEN`,
`LETTA_API_KEY`, `VIBE_TOKEN`).

## Working rules

- Work on copies of Live projects, never the originals.
- Trust the rendered file, not a report: measure its peak.
- Calibrate a measure against a known answer before using it.
- Commit working code the same day. Untracked work gets left behind.
- Keep audio, models and data out of git (see `.gitignore`).
- The vibe server is local-only; its code-changing endpoints need `VIBE_TOKEN`.
