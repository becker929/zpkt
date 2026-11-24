# checklist

A track's checklist across the spine (collage to release), and the worlds I tried around it: the map (a ledger of
stamps and a gallery of plates), the Rummage, the Wasteland, the flow and three earlier concepts. I am not sure yet
how the checklist and the worlds relate, so they are one prototype for now (24 November 2026). They used to live in
the harness at `/studio/checklist/`, and they still answer at that path.

| Page | What it is |
|---|---|
| `/studio/checklist/` | The checklist: HW002's steps and their items (`static/data/hw002.json`). |
| `/studio/checklist/map/` | The map: the checklist as a ledger, its check sounds, the gallery of plates. |
| `/studio/checklist/rummage/` | The Rummage: a region to walk, its machines and their renders. |
| `/studio/checklist/wasteland/` | The Wasteland: the walk to the machine that stands for the track. |
| `/studio/checklist/flow/`, `concepts/` | The earlier rounds. |

Design notes: [studio-agent.md](../../contrib/docs/design/studio-agent.md),
[rummage.md](../../contrib/docs/design/rummage.md), [wasteland.md](../../contrib/docs/design/wasteland.md),
[artist-agent.md](../../contrib/docs/design/artist-agent.md).

## Run

```bash
cd prototypes/checklist
uv run python server.py          # http://127.0.0.1:8798/studio/checklist/
```

The pages call three things the harness ([`contrib/harness`](../../contrib/harness/)) still keeps: the artist
agent's API, the regions' state and renders, and the site's audio. `server.py` serves them in-process from the
harness's library, with the harness's own data, so the plates and regions are the same ones. `--data DIR` keeps
everything in DIR instead, and `--no-model` makes the artist's quick question come from its rules rather than a
small Claude model. It listens on loopback only and asks for no password.

`scripts/cutout.py` cuts the Rummage's sprites out of images made with the image wall
([becker929/image-wall](https://github.com/becker929/image-wall)).

## Test

```bash
uv run --extra dev playwright install chromium webkit
uv run --extra dev pytest                 # the pages in a browser, and server.py over HTTP
uv run --extra dev pytest -m "not ui"     # without a browser
```

`test_map_sounds.py` plays the real check sounds, so it fetches them from the site once.
