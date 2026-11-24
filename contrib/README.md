# contrib

My own setup around the core. These parts run on my Mac every day, but they are tied to my
site, my accounts and my rig. They are here to read and borrow from, not to install as they are.

| Folder | What it is | Tied to |
|---|---|---|
| [`harness/`](harness/) | The Mac end of my phone: Gemini CLI sessions, the HW002 lab, the artist agent's API, behind a password on my tailnet. | anthonybecker.me, Keychain secrets, Hammerspoon |
| [`mixdesk/`](mixdesk/) | The HW002 finishing desk: the Live set's mix on one screen and on the MiniLab 3, A/B/C monitoring, history, recipes. | my HW002 set, MiniLab 3 |
| [`arranger/`](arranger/) | The HW002 arranger: loops bounced from Live arranged on a phone page, with transitions, mix and kick pages. Writes the arrangement file the mix desk adds to. | my HW002 set |
| [`humming/`](humming/) | A humming transcriber: a hummed idea to notes, tempo and key. Research; no CLI. | — |

Two parts left on 24 November 2026 for private repos of their own, with their history. They use zpkt as a
dependency for making music:

- `becker929/music-bot`: the Bluesky music bot, its booth (scores in, Live renders out; the only way the bot
  reaches Live), their contracts (`score.schema.json`, `booth-*.schema.json`) and the bot's design note.
- `becker929/zpkt-demo`: the tools that made the 33-second zpkt demo video from a screen recording of Live.

My workflow, the design notes for these parts and a dated journal are in [`docs/`](docs/). The security model they share
(loopback only, a secret on everything) is in [`SECURITY.md`](../SECURITY.md).

Tests: `make test-all` from the repo root runs every part here that has a suite.
