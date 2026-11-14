# Gemini CLI in zpkt

Anthony, 13 November 2026: integrate Gemini with zpkt directly, with Gemini CLI. It is a second agent in the repo,
beside Claude Code, and he can reach it two ways:

- **On the Mac:** run `harness gemini` in a terminal. Every argument goes to Gemini CLI as it is, for example
  `harness gemini -p "..." -m gemini-flash-latest` or `harness gemini --resume latest`.
- **On the phone:** open `/studio/gemini/` on the Mac's tailnet address, behind the harness password. It replaces the
  read-only chat that was there before, and the standalone chat on tailnet :8789.

## How zpkt is set up for it

- **Rules:** `.gemini/settings.json` makes Gemini CLI read `AGENTS.md`, which links to `CLAUDE.md`. Both agents get
  the same rules: Live through `hands`, images only through `harness images`, and nothing personal in the core.
- **Skills:** `.agents/skills/` links to the skills in `agent/skills/`, as `.claude/skills/` does for Claude Code.
- **Key:** `harness gemini` and the page both take the key from the Keychain's `zpkt-gemini-api-key` (or
  `HARNESS_GEMINI`), the same key the images use. They put it only in Gemini CLI's environment, and never write it
  to a file or send it to the browser.
- **Trust:** the wrapper marks the checkout trusted (`GEMINI_CLI_TRUST_WORKSPACE`), and the page starts Gemini CLI
  with `--skip-trust`.
- **This Mac's settings:** `~/.gemini/settings.json` sets the API key as the way to sign in and turns off Google's
  usage statistics. It lives outside the repo.

## The page

The harness runs one `gemini --acp` process and talks to it in ACP (Agent Client Protocol: JSON-RPC on its stdio).
It starts the process on first use and starts it again if it dies. Gemini CLI works in the checkout the harness runs
from, with its own tools: it reads, edits, runs shell commands and drives Live through `hands`.

- **Modes**, chosen per session above the composer:
  - **Asks first** (the default): every edit and command waits for an answer on the phone, and a notification goes
    out through ntfy. A question shows the tool, its diff or command, and the options Gemini CLI offers: allow once,
    allow for the session, or reject. Allowing for the session switches the session to auto-edit, and the page
    follows.
  - **Auto-edit:** edits go through without asking; commands still ask.
  - **YOLO:** everything goes through without asking. The page asks for a confirmation before switching to it.
  - **Read-only** (Gemini CLI's plan mode): reading only.
- **A turn runs on the Mac.** Closing the page doesn't stop it. Opening the page again shows everything so far and
  follows what comes next. The stop button cancels the turn.
- **On screen:** the answer as it streams, Gemini's thinking (folded away), each tool call with its status and its
  diff or output, and its plan. **Send to Claude** under each answer starts a Claude Code job with the question and
  the answer.
- **Sessions last across restarts.** Gemini CLI keeps each session in `~/.gemini`. After the harness restarts, the
  first message in an old session loads it into the new process. Gemini CLI deletes sessions after 30 days by
  default (`general.sessionRetention`). An older session still shows on the page but can no longer go on.
- **Costs:** each turn's tokens are logged with an estimate in dollars, at the standard rates in
  `harness/gemini.py`. Each answer shows its cost. The side panel shows the month's total for Gemini CLI and for
  images (every image in `images.jsonl`, whoever made it). The real bill is on the AI Studio and Cloud Billing
  pages, because the key cannot read billing.

## Where things are

- **Code:** `contrib/harness/src/harness/gemini.py` (the wrapper, the ACP client, the sessions, the estimate) and
  `contrib/harness/src/harness/studio/gemini_routes.py` (the routes, listed at its top).
- **Page:** `contrib/harness/src/harness/studio/static/gemini/`.
- **Tests:** `contrib/harness/tests/test_gemini.py`, against a fake Gemini CLI that speaks ACP
  (`tests/fake_gemini_acp.py`).
- **Data:** under `HARNESS_STUDIO/gemini` (default `~/_agent_scratch/studio/gemini`):
  - `sessions/<id>.json`: what the page knows of each session: title, model, mode, its folder.
  - `events/<id>.jsonl`: what the page shows, one numbered event per line. An event that changes an earlier one (a
    tool's status, an answered question) names it in `of`.
  - `files/<id>/`: images attached from the phone. They are sent to Gemini inline.
  - `usage.jsonl`: one line per turn.
- **Settings:** `HARNESS_GEMINI_CMD` replaces the `gemini` command.
