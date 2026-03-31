# ears — Audio Perception Layer

`ears` gives the agent the ability to listen. It takes an audio file and
produces a structured `AudioProfile`: spectral features, loudness, rhythm,
DCLAP embeddings, and an optional natural-language description.

## Architecture

| Module | Responsibility |
|--------|---------------|
| `models.py` | `AudioProfile`, `SimilarityResult` — Pydantic v2 |
| `analyzer.py` | Orchestrator: audio path → `AudioProfile` |
| `similarity.py` | Pairwise profile comparison |
| `cli.py` | `ears analyze / compare / batch / describe` |

Audio analysis modules (`features.py`, `loudness.py`, `rhythm.py`, etc.)
will be migrated from `taste 2/audio/` in Phase 2.

## Quick Start

```bash
uv pip install -e .
ears analyze render.mp3 --output profile.json
ears compare render_v1.mp3 render_v2.mp3
```

## Cross-Repo Interface

- **Consumes**: audio files (← hands)
- **Produces**: `AudioProfile` JSON (→ taste)
- **No Python imports** from `hands` or `taste`

## JSON Schemas

- `schemas/audio-profile.schema.json`

## Testing

```bash
uv run pytest
```

All tests run without audio files, ML models, or network access.
