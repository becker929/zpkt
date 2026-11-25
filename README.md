# zpkt

Tools for making techno in Ableton Live 12 with an agent at the controls. I built zpkt to
finish my own tracks: an agent changes the set, renders it, measures the render and shows me
the result, and I decide by ear.

The core is one Python package, `zpkt`, in two halves you can use on their own:

| Part | What it does | Start here |
|---|---|---|
| [`zpkt.live`](src/zpkt/live/) | Drives Live from Python or the shell: run code against the open set, set knobs, edit time, export audio, edit `.als` files offline. | `zpkt live ping` |
| [`zpkt.audio`](src/zpkt/audio/) | Measures a render with calibrated meters (loudness, true peak, dynamics, spectra, a mix against references), and places it among your own reference tracks with a profile and an embedding. Its mastering lab is [`ears/mlab/`](ears/mlab/). | `zpkt audio measure take.wav` |
| [`zpkt.app`](src/zpkt/app/) | The one interface and the one door to Live. It grew from the mix desk's server: the Hear bar, the Desk and Pages, the Song, Options, Ask (Claude and Gemini), the MiniLab, and an API for the `zpkt` command, the booth and the demos. Everything else is its client. | `zpkt app` |
| [`agent/`](agent/) | Skills and rules that let Claude Code (or another agent) drive Live through `zpkt live` without crashing it. | open the repo in Claude Code |

macOS only. You need Ableton Live 12 and [uv](https://docs.astral.sh/uv/). The repo is one uv
project, so nothing is installed globally. Each half has an extra: `zpkt[live]` is light,
`zpkt[audio]` brings librosa, scipy and onnxruntime. Another repo can depend on it by git URL:
`zpkt[live] @ git+https://github.com/becker929/zpkt`.

### The old names

Until 24 Nov 2026 the halves were two projects, `hands` and `ears` (and the meters a third,
`mlab`). The old names still work, as commands and as imports, so skills, scripts and habits keep
working for a while:

| Old | New |
|---|---|
| `hands ...` (command) | `zpkt live ...` |
| `ears ...` (command) | `zpkt audio ...` |
| `mlab ...`, `python -m mlab` | `zpkt audio ...` (the same meter commands); `mlab` is kept as is |
| `import hands.X` | `zpkt.live.X` |
| `import hands.live.X` | `zpkt.live.X` (flattened; `hands.live.cli` is `zpkt.live.live_cli`) |
| `import ears.X`, `ears.meters.X` | `zpkt.audio.X`, `zpkt.audio.meters.X` |
| `import mlab.X` | `zpkt.audio.meters.X` |

An old name gives the same module object, not a copy (`hands.live.state is zpkt.live.state`).
New code imports `zpkt`. [`src/zpkt/live/README.md`](src/zpkt/live/README.md#module-map) has the full module map.

## Ten-minute first run

```bash
git clone https://github.com/becker929/zpkt && cd zpkt
uv sync --all-extras
src/zpkt/live/remote_scripts/install.sh
```

Start (or restart) Live. In Settings → Link, Tempo & MIDI, pick **AbletonLiveMCP** as a Control
Surface on a free row, with Input and Output set to None. Then:

```bash
uv run zpkt live ping                                 # pong in 200 ms
uv run zpkt live exec "result = song.tempo"           # any Python against Live's object model
uv run zpkt live export take.wav --start 8 --length 32    # 32 beats through Live's Export dialog
uv run zpkt audio measure ~/Music/zpkt/renders/take.wav   # calibrated loudness, true peak, dynamics, spectra
uv run zpkt audio analyze ~/Music/zpkt/renders/take.wav   # a profile: band shares, spectra, an embedding
```

[docs/getting-started.md](docs/getting-started.md) walks through each step, the permissions
macOS asks for, and what to do when a step fails.

## How the parts fit

`zpkt.live` acts and `zpkt.audio` measures. Neither imports the other; they exchange files and
JSON, and the JSON is pinned by schemas in [`lib/contracts/`](lib/contracts/). An agent sits on
top and calls both through their CLIs.

`zpkt.app` sits above both and owns the connection to Live. Adapters (the web, the MiniLab, the agents, the API) turn
what they hear into commands; one bus stamps who sent each, runs the checks (who, the agent rule, the wrong-set
guard, the lock) and logs it. The libraries never open a connection. The changing `zpkt` commands go through the app
and refuse when it is not running; `--direct` or `ZPKT_LIVE_VIA=direct` is the old way, and it is not recorded. Read
[src/zpkt/app/README.md](src/zpkt/app/README.md) before changing it.

Two rules keep the loop honest:

- **Trust the rendered file, not a report.** After every change that matters, export and measure.
- **Anything measurable is a measurement.** Loudness, peak and distance from references are
  `zpkt audio`'s job. What is left for a person is taste: choosing between versions that already pass.

I work through a track in seven steps: audio collage, drums, arrange, kick, mix, master,
release ([contrib/docs/workflow.md](contrib/docs/workflow.md)). `zpkt live library inventory` reads a folder of Live
projects and says where each track is in those steps.

## What is in the repo

| Folder | What | Status |
|---|---|---|
| [`src/zpkt/`](src/zpkt/), [`tests/`](tests/), `agent/` | The package and its tests, and the skills. | Supported. Tests run on every push. |
| [`hands/`](hands/), [`ears/`](ears/) | What is not Python package code: the rig's Hammerspoon macros, `hands/bin/hands`, examples and the schema tools; the mastering lab (`ears/mlab/`: guides, reports, calibration checks). | Supported. |
| [`lib/rig/`](lib/rig/) | Brings Live up on a headless Mac (virtual display, audio clock check). | Supported; written for my Mac mini. |
| [`lib/contracts/`](lib/contracts/) | The JSON schemas the parts exchange. | Supported. |
| [`contrib/`](contrib/) | My own setup around the core: phone pages for Gemini and the HW002 lab, the HW002 mix desk and arranger. The Bluesky music bot and its render booth, and the demo video tools, moved to their own private repos ([`contrib/README.md`](contrib/README.md)). | Works on my Mac. Read it for ideas; expect to adapt it. |
| [`prototypes/`](prototypes/) | Experiments beside the main path: a sound-library browser. | Runs; it says what state it is in. |
| [`docs/`](docs/) | The getting-started guide. My workflow, design notes and dated journal are in [`contrib/docs/`](contrib/docs/). | |

## Working rules

- Work on copies of Live projects, never the originals.
- Measure the rendered file's peak before you believe a render worked. A silent bounce looks
  fine in every log.
- Calibrate a measure against a known answer before you use it (`zpkt audio calibrate`).
- Keep audio, models and data out of git (see `.gitignore`).
- Every service listens on loopback only and needs a secret ([SECURITY.md](SECURITY.md)).
  `zpkt live` runs arbitrary Python inside Live, so anything that can reach it can run code as you.

## Tests

```bash
make test        # zpkt.live and zpkt.audio (the calibrated meters too): no Live, no audio files, no network
make test-all    # every part, contrib and prototypes included
```

## More

- The design and its history are written up on
  [anthonybecker.me](https://anthonybecker.me/notes/three-eras/) (notes 15 to 19).
- zpkt grew out of several repos (hands, ears, taste, autodaw, hammerspoon-config). Every import
  kept its history: `git log --follow -- <file>` goes back to 2025.
- The Remote Script in `src/zpkt/live/remote_scripts/AbletonLiveMCP/` is from
  [opendining/ableton-mcp-server](https://github.com/opendining/ableton-mcp-server) (MIT).

MIT licensed ([LICENSE](LICENSE)).
