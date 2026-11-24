# Security

zpkt drives Ableton Live, which can run arbitrary Python as the user. Anything
that can reach a control surface can run code on the Mac. The rule is simple:
**every service listens on loopback only and requires a secret**.

## Services and their guards

| Service | Default bind | Guard | Secret |
|---|---|---|---|
| AbletonLiveMCP remote script (in Live) | 127.0.0.1:16619 | raw TCP, loopback only | — |
| audio-browser API (`prototypes/audio-browser`) | 127.0.0.1:8090 | CORS limited to localhost, tailnet and `*.ts.net` origins | — |
| checklist prototype (`prototypes/checklist/server.py`) | 127.0.0.1:8798 | loopback only, no secret: it serves pages and writes only the artist's and the regions' records | — |
| harness (`contrib/harness`) | 127.0.0.1:8787, on the tailnet through `tailscale serve` | a password per browser (scrypt hashes only, `auth.json` mode 600); every route but `/login` needs the session cookie | the password |

The music bot's booth (127.0.0.1:8794, a token on every request) left with the bot for the private repo
`becker929/music-bot` on 24 November 2026; its guard is documented there.

To reach a service from another device, bind it to the machine's Tailscale
address, not `0.0.0.0`, and add that host to the relevant allow-list
(`DEV_ORIGINS`).

## Agents

- Agents that act on outside input run with least privilege: no blanket
  `bypassPermissions`.
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
