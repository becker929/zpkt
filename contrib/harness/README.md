# harness

The Mac end of my phone. `harness serve` puts a few pages on my tailnet, behind a password: Gemini CLI sessions in
zpkt, the HW002 lab, the artist agent's API, and my site's /skrng pages. It is a temporary home: these parts will be
folded into zpkt's one interface, and the harness will go.

On 24 November 2026 I took out what I no longer use: the spoken studio chat (and `contrib/voice`), Claude Code jobs
and their RPC, and the render feedback. The checklist and its worlds moved to
[`prototypes/checklist`](../../prototypes/checklist/), and the images tool to its own repo,
[becker929/image-wall](https://github.com/becker929/image-wall). Git tag `pre-upgrade-2026-11-24` has it all.

```
phone (Tailscale on) --https--> tailscale serve (tailnet only) --> 127.0.0.1:8787  harness serve
                                                                    ├─ /studio/          a home page linking the rest
                                                                    ├─ /studio/gemini/   Gemini CLI sessions over ACP
                                                                    ├─ /studio/lab/      HW002's controls as surfaces
                                                                    ├─ /studio/api/...   the artist agent, the regions
                                                                    └─ /skrng/           the site's pages, keyless here
```

## What it serves

| Path | What |
|---|---|
| `/` | Redirects to `/studio/`. |
| `/login` | The password: the first visit sets it, later visits sign in. Every other path needs the cookie. |
| `/studio/` | A home page with links to the rest. |
| `/studio/gemini/` | Gemini CLI sessions in the zpkt checkout: prompts with images, permissions, costs ([gemini.md](../docs/gemini.md)). |
| `/studio/lab/` | The HW002 lab ([lab.md](../docs/design/lab.md)); its audio at `/studio/lab/audio/`. Its in-browser sound stays banned ([sound.md](../docs/sound.md)). |
| `/studio/api/artist/...` | The artist agent: thumbs, quick questions, plates, the repertoire ([artist-agent.md](../docs/design/artist-agent.md)). |
| `/studio/api/regions/<id>/state`, `/studio/regions/<id>/audio/<file>` | A region's state and its renders ([rummage.md](../docs/design/rummage.md)). |
| `/studio/site-audio/<path>` | The site's published audio, from an allowlist, through a local copy. |
| `/skrng/...`, `/style.css`, `/favicon.*` | The site's pages, fetched from it and cached 30 s. They see the tailnet host and drop their key. |
| `/audio/...` | Redirects to the site's audio. |

The checklist prototype's pages call the artist, regions and site-audio routes; its own server mounts them from this
package.

## Commands

```bash
uv run harness serve                       # the server above, on 127.0.0.1:8787
uv run harness gemini [gemini-cli args]    # Gemini CLI in the zpkt checkout, with the key from the Keychain
uv run harness artist show                 # the artist's data: repertoire, plates, the last presses
uv run harness artist propose [--dry-run]  # Claude proposes the next repertoire (real Claude)
uv run harness lab-audio [--set --out]     # HW002's stems and clips for the lab, outside the repo
uv run harness lab-params [--set]          # the lab's 100 parameters, read from the set
uv run harness lab-bars [--set]            # the lab's bar library
```

Run `serve` in tmux, so it inherits tmux's Desktop access (a plain launchd job is refused `~/Desktop` silently):

```bash
tmux new-session -d -s studio 'cd ~/Desktop/zpkt/contrib/harness && while :; do uv run harness serve >> ~/_agent_scratch/jobs/harness.log 2>&1; sleep 5; done'
tailscale serve --bg --https=443 http://127.0.0.1:8787
```

## Settings (environment)

| Variable | Default | What |
|---|---|---|
| `HARNESS_WEB_PORT` | `8787` | the loopback port |
| `HARNESS_SITE` | `https://anthonybecker.me` | where /skrng, /audio and site-audio come from |
| `HARNESS_SKRNG` | `~/_agent_scratch/skrng` | `auth.json`: the password's and sessions' hashes (mode 600) |
| `HARNESS_STUDIO` | `~/_agent_scratch/studio` | `artist/`, `regions/`, `gemini/` |
| `HARNESS_STUDIO_WORKDIR` | the zpkt checkout | where Gemini CLI sessions work |
| `HARNESS_STUDIO_MODEL` | Claude Code's default | the model `artist propose` asks |
| `HARNESS_NARRATOR_MODEL` | `claude-haiku-5-5` | the small model of the artist's quick question |
| `HARNESS_CLI` | the SDK's own Claude Code | the `claude` binary for those two |
| `HARNESS_LAB_AUDIO` | `~/_agent_scratch/lab/audio` | the lab's audio |
| `HARNESS_SITE_AUDIO` | `~/_agent_scratch/studio/site-audio` | site-audio's local copies |
| `HARNESS_REGIONS_AUDIO` | `~/_agent_scratch/studio/regions` | the regions' renders |
| `HARNESS_IMAGES` | `~/_agent_scratch/studio/images` | the image wall's folder, read for Gemini's monthly spend |
| `HARNESS_GEMINI_CMD` | `gemini` on PATH | how to start Gemini CLI |

Secrets come from the login Keychain (account `$USER`), never from files or command lines: `zpkt-gemini-api-key`
(Gemini), `zpkt-claude-oauth` (optional: a `claude setup-token` login for the artist's Claude calls), and
`zpkt-ntfy-topic` (the phone notification when Gemini asks a question). Each can be overridden in the environment as
`HARNESS_GEMINI`, `HARNESS_OAUTH` or `HARNESS_NTFY_TOPIC`.

## Test

```bash
uv run --extra dev playwright install chromium webkit
uv run --extra dev pytest                  # everything (about 20 s)
uv run --extra dev pytest -m "not ui"      # without a browser
```

Tests run offline: the site is a local fake, Gemini CLI is `tests/fake_gemini_acp.py`, and the artist's question
comes from its rules. Every route is tested through a real server on a free port. `tests/ui/lab_server.py` serves
the pages without the login, for the lab's browser tests and for trying the lab by hand.

## Security

- Tailnet only, then the password. Only scrypt hashes of the password and of each browser's session are stored,
  so nobody else, Claude included, ever sees it. API routes answer 401 rather than redirecting.
- Gemini CLI sessions can change the checkout: in the default mode every edit and command waits for a yes on the
  phone.
