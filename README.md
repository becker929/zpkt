# zpkt

Tools for making techno in Ableton Live 12 with an agent at the controls. I built zpkt to
finish my own tracks: an agent changes the set, renders it, measures the render and shows me
the result, and I decide by ear.

It is three things you can use on their own:

| Part | What it does | Start here |
|---|---|---|
| [`hands/`](hands/) | Drives Live from Python or the shell: run code against the open set, set knobs, edit time, export audio, edit `.als` files offline. | `hands live ping` |
| [`ears/`](ears/) | Measures a render: loudness, true peak, spectra, an embedding, and its distance from your own reference tracks. [`ears/mlab/`](ears/mlab/) adds calibrated mastering meters. | `ears analyze take.wav` |
| [`agent/`](agent/) | Skills and rules that let Claude Code (or another agent) drive Live through `hands` without crashing it. | open the repo in Claude Code |

macOS only. You need Ableton Live 12 and [uv](https://docs.astral.sh/uv/). Each part is its own
uv project, so nothing is installed globally.

## Ten-minute first run

```bash
git clone https://github.com/becker929/zpkt && cd zpkt
hands/remote_scripts/install.sh
```

Start (or restart) Live. In Settings → Link, Tempo & MIDI, pick **AbletonLiveMCP** as a Control
Surface on a free row, with Input and Output set to None. Then:

```bash
cd hands
uv run hands live ping                                # pong in 200 ms
uv run hands live exec "result = song.tempo"          # any Python against Live's object model
uv run hands live export take.wav --start 8 --length 32   # 32 beats through Live's Export dialog
cd ../ears
uv run ears analyze ~/Music/zpkt/renders/take.wav     # loudness, true peak, band energy, spectra
```

[docs/getting-started.md](docs/getting-started.md) walks through each step, the permissions
macOS asks for, and what to do when a step fails.

## How the parts fit

`hands` acts and `ears` measures. Neither imports the other; they exchange files and JSON, and
the JSON is pinned by schemas in [`lib/contracts/`](lib/contracts/). An agent sits on top and
calls both through their CLIs.

Two rules keep the loop honest:

- **Trust the rendered file, not a report.** After every change that matters, export and measure.
- **Anything measurable is a measurement.** Loudness, peak and distance from references are
  `ears`' job. What is left for a person is taste: choosing between versions that already pass.

I work through a track in seven steps: audio collage, drums, arrange, kick, mix, master,
release ([docs/workflow.md](docs/workflow.md)). `hands library inventory` reads a folder of Live
projects and says where each track is in those steps.

## What is in the repo

| Folder | What | Status |
|---|---|---|
| `hands/`, `ears/`, `agent/` | The three parts above. | Supported. Tests run on every push. |
| [`lib/rig/`](lib/rig/) | Brings Live up on a headless Mac (virtual display, audio clock check). | Supported; written for my Mac mini. |
| [`lib/contracts/`](lib/contracts/) | The JSON schemas the parts exchange. | Supported. |
| [`contrib/`](contrib/) | My own setup around the core: a phone voice app, a Bluesky music bot and its render booth, publishing to my site. | Works on my Mac. Read it for ideas; expect to adapt it. |
| [`prototypes/`](prototypes/) | Experiments beside the main path: a sound-library browser, a preference judge, an unattended loop, a humming transcriber, research. | Mixed; each says what state it is in. |
| [`docs/`](docs/) | Guides, design notes and a dated [journal](docs/journal/) of the work. | |

## Working rules

- Work on copies of Live projects, never the originals.
- Measure the rendered file's peak before you believe a render worked. A silent bounce looks
  fine in every log.
- Calibrate a measure against a known answer before you use it (`mlab calibrate`).
- Keep audio, models and data out of git (see `.gitignore`).
- Every service listens on loopback only and needs a secret ([SECURITY.md](SECURITY.md)).
  `hands` runs arbitrary Python inside Live, so anything that can reach it can run code as you.

## Tests

```bash
make test        # hands, ears, mlab: no Live, no audio files, no network
make test-all    # every part, contrib and prototypes included
```

## More

- The design and its history are written up on
  [anthonybecker.me](https://anthonybecker.me/notes/three-eras/) (notes 15 to 19).
- zpkt grew out of several repos (hands, ears, taste, autodaw, hammerspoon-config). Every import
  kept its history: `git log --follow -- <file>` goes back to 2025.
- The Remote Script in `hands/remote_scripts/AbletonLiveMCP/` is from
  [opendining/ableton-mcp-server](https://github.com/opendining/ableton-mcp-server) (MIT).

MIT licensed ([LICENSE](LICENSE)).
