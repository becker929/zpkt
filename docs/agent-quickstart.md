# Agent quickstart

Read this first. It is one page. The long docs are at the end.

## What zpkt is

zpkt is a Python package for making techno in Ableton Live 12 on a Mac. An agent changes the set, renders it and
measures the render. A person decides by ear. There are three parts:

- `zpkt.app` is the one door to Live. It queues, locks and records every change.
- `zpkt.live` drives Live: run code against the open set, set knobs, export audio.
- `zpkt.audio` measures a render: loudness, true peak, dynamics, spectra.

## Five commands

Run them from the repo root with `uv run`.

1. `zpkt app` starts the app. Leave it running in its own terminal. Changes to Live need it.
2. `zpkt live check` says which set is in front and whether a dialog is open. Run it before you act.
3. `zpkt live exec "result = song.tempo"` runs Python against Live's object model. Keep each call short.
4. `zpkt live export take.wav --start 8 --length 32` renders 32 beats from beat 8 through Live's Export dialog.
5. `zpkt audio measure take.wav` measures the file. Add `--json` for data.

`zpkt live ping` tests the connection. Reads and `ping` work without the app.

If `ZPKT_AGENT=1` is set, you are an agent: you may read and make pages (`zpkt page make`), and the `zpkt live`
commands that change Live refuse you. To change values or devices, send the app one batch (`live.change`, the
`change_live` tool in Ask: `src/zpkt/app/README.md`, "A batch of changes"). To suggest an alternative to hear, make
a page with compare states (Pages, Compare): your user presses the pad.

## Never

1. Never open your own connection to Live. Go through `zpkt app`. `--direct` skips it and is not recorded.
2. Never work on an original project. Work on a copy. The set must be one of ours (its name starts with
   `zpkt_` by default).
3. Never believe a render worked until you have measured its peak. A silent bounce looks fine in every log.

## Where the long docs are

| Need | Read |
|---|---|
| Install and a first export | [getting-started.md](getting-started.md) |
| Rules for editing this repo | [`../CLAUDE.md`](../CLAUDE.md) |
| The app: bus, web, API, Pages and compare states | [`../src/zpkt/app/README.md`](../src/zpkt/app/README.md) |
| Driving Live: modules, commands, settings | [`../src/zpkt/live/README.md`](../src/zpkt/live/README.md) |
| What crashes Live from LOM code | [`../agent/skills/ableton-guide/SKILL.md`](../agent/skills/ableton-guide/SKILL.md) |
| Measuring renders | [`../src/zpkt/audio/README.md`](../src/zpkt/audio/README.md) |
