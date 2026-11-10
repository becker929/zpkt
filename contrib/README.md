# contrib

My own setup around the core. These parts run on my Mac every day, but they are tied to my
site, my accounts and my rig. They are here to read and borrow from, not to install as they are.

| Folder | What it is | Tied to |
|---|---|---|
| [`harness/`](harness/) | The Mac end of my phone: **studio** (a voice app for producing by talking), Claude Code jobs started from the browser, the checklist and lab pages. | anthonybecker.me, Keychain secrets, Hammerspoon |
| [`voice/`](voice/) | Speech in and out for studio: Kokoro and Parakeet workers, a pronunciation lexicon, the benchmark behind the choice. | Apple Silicon |
| [`booth/`](booth/) | Takes a score (JSON) and renders it in Live with a fixed palette of instruments. The only way the bot reaches Live. | my Live library |
| [`bot/`](bot/) | A Bluesky account that makes short pieces for people who mention it, by writing scores for the booth. | Bluesky, Anthropic API |
| [`skrng/`](skrng/) | Publishing renders to /skrng on my site, and fetching models from my bucket. | my R2 bucket |
| [`letta-vibe/`](letta-vibe/) | An earlier agent: Letta driving Live through an MCP bridge, with a phone page for feedback. Parked. | Letta, Docker |
| [`demo/`](demo/) | The tools that made the 33-second zpkt demo video from a screen recording of Live. | my HW002 set |

My workflow, the design notes for these parts and a dated journal are in [`docs/`](docs/). The security model they share
(loopback only, a secret on everything) is in [`SECURITY.md`](../SECURITY.md).

Tests: `make test-all` from the repo root runs every part here that has a suite.
