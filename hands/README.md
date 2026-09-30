# hands — DAW Control Layer

`hands` gives the agent fine-grained control over Ableton Live 12. It owns
the full pipeline from declarative project configs to executed MCP commands:

```
ProjectConfig (JSON) → codegen → list[Step] → StepRunner → TCP → Ableton Live
```

## Quick Start

```bash
uv pip install -e .
hands build --config examples/simple_kick.py --dry-run
```

## Architecture

| Module | Responsibility |
|--------|---------------|
| `models.py` | `ProjectConfig`, `Feedback` — frozen Pydantic v2; source of truth for JSON schemas |
| `transport.py` | `McpTransport` protocol + `LiveMcpTransport` (TCP, port 16619), `DryRunTransport`, `MockTransport` |
| `codegen.py` | Low-level `gen_*` functions: config values → `Step` (label + LOM Python snippet) |
| `builder.py` | `ProjectBuilder` — sequencing logic; maps config sections to ordered `list[Step]` |
| `runner.py` | `StepRunner` — executes steps with retry, undo rollback, manual prompts, resumability |
| `recorder.py` | Record via resampling track, export WAV or MP3 |
| `helpers.py` | Stateless LOM queries (`get_track_names`, `get_song_state`, etc.) |
| `cli.py` | `hands build / execute / record / vibe` |
| `vibe/` | Human feedback loop: bounce audio, serve for listening, capture feedback |

## CLI Commands

```bash
# Build from config JSON (dry-run by default)
hands build --config examples/simple_kick.json
hands build --config examples/schranz.json --no-dry-run  # executes against Ableton

# Execute against live Ableton (resume from step 14 on error)
hands execute --config schranz.json --resume 14

# Record and export
hands record --beats 64 --output render.wav
hands record --beats 128 --output render.mp3  # requires ffmpeg

# Human feedback loop
hands vibe                    # start vibe server on port 8080
hands vibe --tunnel           # + open ngrok tunnel (requires hands[vibe])
```

## Transport Protocol

All transport implementations share the `McpTransport` protocol:

```python
class McpTransport(Protocol):
    def execute(self, code: str) -> McpResult: ...
```

| Transport | Use case |
|-----------|---------|
| `LiveMcpTransport` | Connects to Ableton MCP server (`127.0.0.1:16619`) |
| `DryRunTransport` | Prints code, never contacts Ableton |
| `MockTransport` | Returns canned `McpResult` queue — offline testing |

## Testing

```bash
uv run pytest           # all 46 tests; runs fully offline
uv run pytest -v        # verbose output
```

All tests use `MockTransport` — no Ableton required.

## Cross-Repo Interface

- **Produces**: `ProjectConfig` JSON (→ taste), audio files (→ ears), `Feedback` JSON (→ taste)
- **Consumes**: Nothing from ears or taste — no Python imports across repos
- **Schemas**: `schemas/project-config.schema.json`, `schemas/feedback.schema.json`

## Vibe Tool

The vibe tool is the producer's hands-on feedback mechanism:

```
Phone (browser) → local HTTP server → bounce Ableton → serve MP3 → capture feedback
```

Start with `hands vibe [--tunnel]`. Endpoints:
- `POST /bounce` — trigger audio recording
- `POST /feedback` — submit text/rating feedback
- `GET  /session` — current session metadata

Letta AI (persistent memory) is optional. Install with `pip install hands[vibe]`.

## Installation

```bash
# Core
uv pip install -e .

# With vibe extras (Letta + ngrok)
uv pip install -e ".[vibe]"
```

## Agent Skill

The Ableton MCP skill lives at `.cursor/skills/ableton-guide/SKILL.md`. Any
agent workspace that clones `hands` gets the LOM reference and crash-avoidance
rules automatically.
