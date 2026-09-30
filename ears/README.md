# ears — Audio Perception Layer

`ears` gives the agent the ability to listen. It takes an audio file and
produces a structured `AudioProfile`: spectral features, loudness, rhythm,
DCLAP embeddings, and an optional natural-language description.

## Architecture

| Module | Responsibility |
|--------|---------------|
| `models.py` | `AudioProfile`, `SimilarityResult` — dataclasses |
| `analyzer.py` | Orchestrator: audio path → `AudioProfile` |
| `similarity.py` | Pairwise profile comparison |
| `loudness.py` | LUFS on the file's real channels, true peak (dBTP, 4x oversampled), band energy |
| `embeddings.py` | DCLAP embedding; model path from `EARS_DCLAP_MODEL` |
| `cli.py` | `ears analyze / compare` |

Embeddings need the DCLAP ONNX model, which is not in this repo. Point
`EARS_DCLAP_MODEL` at `model_epoch_36.onnx`; without it `embedding` is `null`
and `errors` says why.

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
