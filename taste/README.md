# taste — Brain / Taste Model

`taste` is the brain of the system. It closes the loop between the agent's
production actions and human aesthetic judgment. It owns the corpus, the
RAG-based taste judge, and the orchestration logic.

## Architecture

| Module | Responsibility |
|--------|---------------|
| `models.py` | `Verdict`, `FeedbackTuple` |
| `corpus/store.py` | SQLite-backed annotation store |
| `corpus/retrieval.py` | Embedding cosine retrieval for RAG context |
| `judge/taste_model.py` | RAG judge: retrieve → prompt → Verdict |
| `loop/orchestrator.py` | End-to-end `hands → ears → taste` cycle |
| `cli.py` | `taste judge / loop / corpus / eval` |

Source code will be migrated from `taste 2/` in Phase 2.

## How the Taste Model Works

The taste model is not a neural network — it is retrieval-augmented generation:

1. Retrieve top-k most similar corpus entries by embedding cosine similarity
2. Format retrieved entries + the new `AudioProfile` as a structured LLM prompt
3. Call Claude for a structured `Verdict`: score 1–5, rationale, suggestions

The implicit taste model emerges from the growing corpus of human annotations.

## Quick Start

```bash
uv pip install -e ".[judge]"
taste judge profile.json
taste loop --config schranz.json --cycles 5
taste corpus stats
```

## Cross-Repo Interface

- **Consumes**: `AudioProfile` JSON (← ears), `Feedback` JSON (← hands)
- **Produces**: `Verdict` JSON (→ hands for acting on suggestions)
- **No Python imports** from `hands` or `ears`
- Cross-repo calls via CLI subprocess only

## JSON Schemas

- `schemas/verdict.schema.json`

## Testing

```bash
uv run pytest
```

All tests use in-memory SQLite and stub LLM — no API keys required.
