# harness

Claude Code jobs on the Mac, started from the browser.

```
phone (/skrng)  --POST /api/rpc, SKRNG_TOKEN-->  anthonybecker.me Worker
                                                 RigBroker (Durable Object)
Mac: harness serve  ==WebSocket, RIG_TOKEN==>    holds the socket, forwards calls,
     Agent SDK -> Claude Code in ~/Desktop       returns the Mac's answer
```

The Mac listens on nothing. `harness serve` dials
`wss://anthonybecker.me/api/rig/connect` and keeps the socket open. A browser
call is forwarded down it, and the HTTP request stays open until the Mac
answers, so from the browser it is a plain synchronous call. The Worker side is
`src/rig.js` in the site repo.

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
| `zpkt-rig-token` | the Mac's key to the broker | Worker secret `RIG_TOKEN` |
| `skrng-token` | the owner's key (page, feedback API, RPC) | Worker secret `SKRNG_TOKEN` |
| `zpkt-claude-oauth` | `claude setup-token` output | passed to jobs as `CLAUDE_CODE_OAUTH_TOKEN` |
| `zpkt-ntfy-topic` | ntfy.sh topic | — |

The Claude token has to be made once, by Anthony, because it needs a browser
sign-in:

```bash
claude setup-token
security add-generic-password -U -s zpkt-claude-oauth -a "$USER" -w
```

The second command asks for the token. Paste it there, never on a command line.

## Run

Hammerspoon keeps it running (`hands/macros/hammerspoon/modules/harness.lua`,
started from `rig-init.lua`, restarted 30 s after any exit). It is not a
launchd agent: the code and the jobs live in `~/Desktop`, which macOS guards
per app, and a bare launchd job is silently refused there. Hammerspoon already
has Desktop and Accessibility access and its children inherit them.

By hand (from a shell that can read ~/Desktop):

```bash
nohup uv run --project ~/Desktop/zpkt/lib/harness harness serve >> ~/_agent_scratch/jobs/harness.log 2>&1 &
uv run --project lib/harness harness jobs
uv run --project lib/harness harness show <id>
uv run --project lib/harness harness job "say hello"   # one job in the foreground, no socket
uv run --project lib/harness pytest
```

The log is `~/_agent_scratch/jobs/harness.log`. Check it from anywhere with
the page's agent panel, or `POST /api/rpc {"method": "ping"}`.

## Security

- The only inputs are calls carrying the owner's key. The Worker forwards only
  the six methods above, and caps the body at 64 KB.
- The two keys are separate. The browser's key cannot connect as the rig, and
  the rig's key is never sent to a browser.
- `ask` cannot change anything. Jobs can, which is the point. Their prompt is
  either the fixed feedback template or text the owner typed.
- A feedback job treats the transcripts as data about the music. It does not
  take them as commands to the shell.
