# Getting started

From a fresh clone to a measured render. About ten minutes if Live is already installed.

## What you need

- A Mac. zpkt drives Live's windows with AppleScript, so it is macOS only.
- Ableton Live 12 (any edition; I use Suite 12.4).
- [uv](https://docs.astral.sh/uv/). It installs Python and each part's packages on first run.
- For `zpkt live export` only: [cliclick](https://github.com/BlueM/cliclick) (`brew install cliclick`).

## 1. Clone and install the Remote Script

```bash
git clone https://github.com/becker929/zpkt && cd zpkt
src/zpkt/live/remote_scripts/install.sh
```

This copies two Control Surface scripts into `~/Music/Ableton/User Library/Remote Scripts/`:

- **AbletonLiveMCP** is the bridge. It listens on `127.0.0.1:16619` and runs the Python it is
  sent inside Live. It comes from
  [opendining/ableton-mcp-server](https://github.com/opendining/ableton-mcp-server) (MIT).
- **ZpktMiniLabTempo** puts tempo on a fader of an Arturia MiniLab 3. Ignore it if you do not have one.

## 2. Turn the bridge on in Live

Live only finds new Remote Scripts at launch, so quit and reopen it. Then:

1. Open Settings → Link, Tempo & MIDI.
2. On a free Control Surface row, choose **AbletonLiveMCP**.
3. Leave Input and Output at None.

Do not put it on a row that already has a controller.

## 3. Check the connection

From the repo root (`uv sync --all-extras` once; `hands` is the old name of `zpkt live`, `ears` and `mlab` of `zpkt audio`):

```bash
uv run zpkt live ping
```

`pong in 237 ms` means the bridge is up. The first run takes longer while uv builds the
environment.

| You see | Cause | Fix |
|---|---|---|
| `Cannot reach Ableton: Connection refused` | Live is not running, or the Control Surface is not selected. | Step 2. |
| The ping hangs, then times out | Live is showing a dialog, or is still loading a set. | `uv run zpkt live modals` lists dialogs. |

## Start the app for changes

`zpkt app` is the one door to Live. A command that changes Live (`exec` with a write, `export`) goes through it and
refuses when it is not running. Reads and `ping` do not need it. Leave this running in a second terminal:

```bash
uv run zpkt app
```

`--direct` on a command skips the app (it is not recorded). See
[`src/zpkt/app/README.md`](../src/zpkt/app/README.md).

## 4. Read and change the set

`zpkt live exec` runs Python against the Live Object Model. `song` is the open set, and
whatever you assign to `result` comes back.

```bash
uv run zpkt live exec "result = song.tempo"
uv run zpkt live exec "result = [t.name for t in song.tracks]"
uv run zpkt live exec "song.tempo = 140"
```

Live is easy to crash from this side. Before you write anything longer than a line, read the
rules in [`agent/skills/ableton-guide/SKILL.md`](../agent/skills/ableton-guide/SKILL.md). The
short version: keep each call short, never touch the GUI from LOM code, and work on a copy of
your project.

## 5. Export audio

```bash
uv run zpkt live export take.wav --start 8 --length 32
```

This selects 32 beats from beat 8 and drives Live's Export dialog. A bare file name lands in
`~/Music/zpkt/renders/`; give a path to put it elsewhere. The target must not exist yet.

Export clicks through Live's windows, so macOS asks once for two permissions for the app that
runs the command (Terminal, iTerm, or your editor): **Accessibility** and **Automation** (System
Settings → Privacy & Security). The pointer moves during the export and is parked afterwards.

## 6. Measure the render

```bash
uv run zpkt audio analyze ~/Music/zpkt/renders/take.wav
```

You get integrated loudness (LUFS), true peak (dBTP), the share of energy in five bands and a
few spectral measures. Add `--json` for the full `AudioProfile`.

For mastering work, `zpkt audio` has stricter meters and checks them against known answers:

```bash
uv run zpkt audio calibrate                                # 125 known-answer checks (117 with --quick)
uv run zpkt audio measure ~/Music/zpkt/renders/take.wav    # the full measurement sheet
uv run zpkt audio deliver ~/Music/zpkt/renders/take.wav    # what a platform's normalisation and codec do to it
```

## 7. Compare against your own references

Put tracks you want yours to sit among in a folder. Build the corpus once, then place any
render in it:

```bash
uv run zpkt audio corpus build ~/Music/references
uv run zpkt audio corpus distance ~/Music/zpkt/renders/take.wav
```

Each measure is shown against the corpus's median and its 10th to 90th percentile. No reference
audio ships with zpkt.

For an embedding distance and the nearest reference tracks, fetch the embedding model first
(22 MB), then rebuild the corpus:

```bash
ears/scripts/fetch_model.sh
```

## 8. Let an agent drive

Open the repo in [Claude Code](https://claude.com/claude-code). The skills in
[`agent/skills/`](../agent/) are linked into `.claude/skills/`, so the agent already knows how
to reach Live, what crashes it and how to export. Try: *"What tempo is the open set, and which
tracks are muted?"* See [`agent/README.md`](../agent/README.md).

## Settings

What differs per Mac is read from `~/.config/zpkt/rig.toml` or the environment; nothing personal
is in the repo. The defaults put everything under `~/Music/zpkt/`. The keys are listed in
[`src/zpkt/live/README.md`](../src/zpkt/live/README.md#rig-settings).

`zpkt live` commands that change a set on their own (probe kits, plans, time edits) first check that
the front set is "one of ours": its name starts with one of `set_prefixes` (default `zpkt_`). It
is how the tools avoid acting on a set someone else has open. Name your working copies to match,
or set your own prefixes.

Two things about the sets folder, both from Live:

- **It must be a Live Project.** Live refuses to save a set outside one and shows a Save As
  prompt, which stops `zpkt live`. Save a set there once with File → Save Live Set As (Live makes
  the `Ableton Project Info` folder), then copy sets into it freely.
- **Sets must be saved by your version of Live.** A set from an older version also gets a Save
  As prompt on its first save. Open it and save it under a new name before pointing `zpkt live` at it.

Live draws those prompts itself, so `zpkt live modals` can only say that one is open (`OPEN`),
not which. Look at Live when you see it.

## A headless Mac

[`lib/rig/start_headless.sh`](../lib/rig/) brings Live up on a Mac with no screen: a virtual
display (BetterDisplay), no sleep (Caffeine), the window placed, the bridge answering and the
audio clock running. A frozen audio clock means no audio device, and then every render is silent.
