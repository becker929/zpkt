# letta-vibe

A prototype, parked here from `hands/` in October 2026: a Letta agent that drives Ableton Live
through an MCP bridge, a vibe server that bounces audio for listening on a phone and captures
feedback, a Next.js chat frontend, and a watchdog that restarts the stack and can ask the Claude
Agent SDK to fix it.

Nothing on zpkt's main path uses it. The voice loop in `docs/plan-2026-10.md` replaces it with a
Claude Code session and skills, calling the `hands` library directly. It depends on `hands` for
the LOM client (`hands.live.transport.LiveClient`).

| Part | What it is |
|---|---|
| `src/letta_vibe/vibe/` | the vibe server: `/bounce`, `/analyze`, `/feedback`, `/self-improve`, `/restart` |
| `src/letta_vibe/mcp_server.py` | MCP bridge (Streamable HTTP, port 9010) so Letta can run LOM code |
| `src/letta_vibe/self_modify.py` | Claude Agent SDK edits to this prototype, then service restarts |
| `src/letta_vibe/cli.py` | `letta-vibe vibe / ableton-mcp / self-improve` |
| `frontend/` | the Letta chatbot template, adapted (Next.js, Cypress tests) |
| `scripts/` | `setup_letta_tools.py` (registers Letta tools), `stream_agent.py`, `watchdog.py` |
| `Makefile` | `make start / stop / status / logs / test / watchdog` for the whole stack |

The bounce endpoint still imports an `export_offline` module from a folder that is not in zpkt;
`hands live export` is the working export path now.

## Tests

```bash
uv run pytest -q -p no:cacheprovider
# the MCP bridge tests need the optional mcp stack:
uv run --with "mcp>=1.26,<2" --with uvicorn --with starlette --with httpx pytest -q -p no:cacheprovider tests/test_mcp_bridge_security.py
```

## Security

Every service binds loopback and needs a secret (`MCP_BRIDGE_TOKEN`, `LETTA_API_KEY`,
`VIBE_TOKEN`); see the repository's `SECURITY.md`. Self-improve may edit this folder and run
tests only.
