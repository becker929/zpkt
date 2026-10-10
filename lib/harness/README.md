# harness

The Mac end of everything the phone does: **studio** (the voice production app), the /skrng pages, and Claude Code
jobs. `harness serve` runs it all.

```
phone (Tailscale on) --https--> tailscale serve (tailnet only) --> 127.0.0.1:8787  harness serve
                                                                    ├─ /studio/   the voice app (docs/studio.md)
                                                                    ├─ /skrng/    the site's pages, keyless here
                                                                    ├─ /api/rpc   the methods below, in-process
                                                                    └─ jobs       Claude Code sessions, one at a time
```

The server listens on loopback only; `tailscale serve --bg --https=443 http://127.0.0.1:8787` puts it on the tailnet
with an HTTPS certificate (the mic needs a secure page). Nothing reaches it from the public internet. On top of
that it asks for a password once per browser: the first visit sets it, later visits sign in with it. Only scrypt
hashes of the password and of each browser's session are stored (`auth.json`, mode 600), so nobody else, Claude
included, ever sees it. `/` opens studio.

The older public route (browser → anthonybecker.me Worker → RigBroker socket → Mac) is off unless
`HARNESS_PUBLIC_RPC=1`; the Worker side is `src/rig.js` in the site repo.

## studio

The voice production app: a chat with one long-lived Claude Code session (cwd: zpkt), spoken both ways, with music
and screenshots as their own bubbles. Its design, turn model and protocol are in `docs/studio.md`; the code is
`src/harness/studio/`, and the speech models run in their own process (`lib/voice`), started and restarted by the
harness. Its data (SQLite chat, media) lives in `~/_agent_scratch/studio/` (`HARNESS_STUDIO`).

Settings (environment):

| Variable | Default | What |
|---|---|---|
| `HARNESS_STUDIO` | `~/_agent_scratch/studio` | chat database and media |
| `HARNESS_STUDIO_WORKDIR` | the zpkt checkout | the Claude session's working directory |
| `HARNESS_STUDIO_MODEL` | Claude Code's default | the session's model |
| `HARNESS_NARRATOR_MODEL` | `haiku` | the model that narrates tool activity |
| `HARNESS_TTS_VOICE`, `HARNESS_TTS_SPEED` | `af_heart`, `1.0` | Kokoro voice |
| `HARNESS_STOP_WORD` | `tomato` | the word that ends a spoken turn |
| `HARNESS_VOICE_CMD` | `uv run --project lib/voice --extra engines voice serve` | how to start the speech worker |
| `HARNESS_STEPS_PORT` | `8788` | loopback port where scripts report steps (for screenshots) |

## RPC methods (`POST /api/rpc`)

| Method | Params | Returns |
|---|---|---|
| `ping` | — | `{ok, host, running, queued}` |
| `ask` | `{prompt}` | `{answer, session_id}`; a read-only session (Read, Glob, Grep), within two minutes |
| `feedback` | `{batch, session?, note?}` | `{job_id}`; queues a job that reads that batch's answers and acts on them |
| `job` | `{prompt, title?}` | `{job_id}`; a free-form job |
| `job_status` | `{id, tail?}` | the job and its last steps |
| `jobs` | `{n?}` | recent jobs |

## Jobs

- **What a job is.** One Agent SDK session, with cwd `~/Desktop`. It loads the
  same CLAUDE.md files and auto-memory as a desktop session.
- **Tools.** Bash, Read, Write, Edit, Glob, Grep, NotebookEdit, WebFetch,
  WebSearch, TodoWrite and Task, with edits auto-accepted. Nobody is there to
  approve anything else, so anything else is denied.
- **Desktop-only tools are not available.** That means the in-app browser,
  computer use and the iOS simulator. Live is still reachable, because it is
  driven over TCP and osascript.
- **One at a time.** Jobs share one Live instance, so they never overlap.
- **Notifications.** ntfy sends one when a job starts and one when it
  finishes, with the job's final message. Tapping either opens
  `/skrng/#jobs`.
- **Records.** Each job is kept in `~/_agent_scratch/jobs/<id>/`:
  `job.json` (status, result, session id, cost) and `events.jsonl` (what the
  job said and which tools it used).
- **Continuing a job.** Resume its session from the Mac:
  `cd ~/Desktop && claude --resume <session_id>`. The page shows that line.
- **Restarts.** A job that was running when the harness restarted is marked
  failed. Queued jobs run after the restart.
- **The voice review starts a job.** When a review ends with answers, the page
  waits until every answer is on the site, then calls `feedback`. A second call
  for the same batch, made before the first job starts, joins it rather than
  queueing a new one.

## Secrets (login Keychain, account `$USER`)

| Keychain service | What | Also set as |
|---|---|---|
| `zpkt-rig-token` | the Mac's key to the broker (public route only) | Worker secret `RIG_TOKEN` |
| `skrng-token` | the owner's key on the public site | Worker secret `SKRNG_TOKEN` |
| `zpkt-claude-oauth` | `claude setup-token` output (optional) | passed to sessions as `CLAUDE_CODE_OAUTH_TOKEN` |
| `zpkt-ntfy-topic` | ntfy.sh topic | — |

Without `zpkt-claude-oauth`, sessions use the Mac's own `claude` login. To make one (it needs a browser sign-in):

```bash
claude setup-token
security add-generic-password -U -s zpkt-claude-oauth -a "$USER" -w
```

The second command asks for the token. Paste it there, never on a command line.

## Run

Run it in tmux, so it inherits tmux's macOS permissions: Desktop access (the code lives there) and Screen Recording
(studio's screenshots). A plain launchd job is refused ~/Desktop silently, and a process without Screen Recording
captures only the wallpaper.

```bash
tmux new-session -d -s studio 'cd ~/Desktop/zpkt/lib/harness && while :; do uv run harness serve >> ~/_agent_scratch/jobs/harness.log 2>&1; sleep 5; done'
uv run --project lib/harness harness jobs
uv run --project lib/harness harness show <id>
uv run --project lib/harness harness job "say hello"   # one job in the foreground, no socket
uv run --project lib/harness pytest
```

The log is `~/_agent_scratch/jobs/harness.log`.

## Security

- Tailnet only, then the password. Every route except `/login` needs a signed-in session cookie, the studio
  WebSocket included; API routes answer 401 rather than redirecting.
- studio's step endpoint (for scripts) listens on loopback only, on a port `tailscale serve` does not forward, and
  needs a token made fresh at each start and given only to Claude's environment.
- `ask` cannot change anything. Jobs and the studio session can, which is the point: they act for the owner.
- A feedback job treats the transcripts as data about the music. It does not take them as commands to the shell.
- With the public route on, the Worker forwards only the six RPC methods and caps the body at 64 KB; the browser's
  key cannot connect as the rig, and the rig's key is never sent to a browser.
