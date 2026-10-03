# Security

zpkt drives Ableton Live, which can run arbitrary Python as the user. Anything
that can reach a control surface can run code on the Mac. The rule is simple:
**every service listens on loopback only and requires a secret**.

## Services and their guards

| Service | Default bind | Guard | Secret |
|---|---|---|---|
| AbletonLiveMCP remote script (in Live) | 127.0.0.1:16619 | raw TCP, loopback only | — |
| MCP bridge (`hands ableton-mcp`) | 127.0.0.1:9010 | bearer token, DNS-rebinding host/origin allow-list; refuses to start without a token | `MCP_BRIDGE_TOKEN` |
| Letta (Docker, `make start-letta`) | 127.0.0.1:8283 | server password; keys passed via a private env file | `LETTA_API_KEY` |
| vibe server (`hands vibe`) | 127.0.0.1:8080 | Host and Origin allow-lists, JSON-only POSTs, 1 MB body cap; `/self-improve` and `/restart` need the token; with `--tunnel`, every endpoint does | `VIBE_TOKEN` |
| hands frontend (Next.js) | 127.0.0.1:3000 | Host allow-list in middleware; agent PATCH limited to `name` | — |
| audio-browser API | 127.0.0.1:8090 | CORS limited to localhost, tailnet and `*.ts.net` origins | — |
| taste annotation app | 127.0.0.1 | file serving confined to the clips folder | — |
| harness (`lib/harness`) | listens on nothing; dials out to anthonybecker.me | the site forwards six RPC methods, and only with the owner's key; ask sessions are read-only | `RIG_TOKEN`, `SKRNG_TOKEN` |

To reach a service from another device, bind it to the machine's Tailscale
address, not `0.0.0.0`, and add that host to the relevant allow-list
(`VIBE_ALLOWED_HOSTS`, `FRONTEND_ALLOWED_HOSTS`, `DEV_ORIGINS`).

## Agents

- Agents that act on outside input run with least privilege: no blanket
  `bypassPermissions`. Self-improve may edit `hands/` and run tests only.
- Text from logs, comments or messages is untrusted data. The watchdog wraps
  logs as such; the mailbox poller only accepts comments from allow-listed
  accounts (`MAILBOX_ALLOWED_AUTHORS`).
- The code-changing endpoints' token is never given to an LLM-driven tool.

## Secrets

Never commit secrets: `.env` and `local.env` are ignored, templates hold
placeholders, and CI plus GitHub secret scanning check every push. Secrets are
read from the macOS Keychain or the environment and are kept off command
lines. Audio, models and data stay out of git (see `.gitignore`).

## Reporting

Report a vulnerability privately through GitHub's "Report a vulnerability"
button on this repository's Security tab.
