# contrib/voice

Speech for studio, my voice production app (`contrib/harness`, design in
`contrib/docs/design/studio.md`). The models run in their own process so the app stays responsive:
`voice serve` reads requests on stdin and writes replies on stdout (`src/voice/protocol.py`).

- Text to speech: Kokoro.
- Speech to text: Parakeet on MLX, with a stop word that ends a turn.
- `lexicon/` holds pronunciations for words the models get wrong.
- `bench/` and `contrib/docs/design/voice-benchmark.md` record how the models were chosen.

```bash
uv run --extra engines voice serve              # the real models (Apple Silicon)
uv run voice serve --tts fake --stt fake        # no models: for tests and page work
uv run --extra dev pytest
```
