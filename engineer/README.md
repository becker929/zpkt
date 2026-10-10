# engineer

Decides what to try next and runs it. It uses the other three parts: it
asks `hands` to act, `ears` to measure and `taste` to judge.

| Module | What it does |
|---|---|
| `src/engineer/loop.py` | One cycle: `hands execute/record` → `ears analyze --json` → `taste` judge |
| `src/engineer/search/` | Optimisers. `serum_evolver` and `ga_jsi` are autodaw's 2025 genetic algorithm and pairwise-preference code, kept for reference and not wired in yet |

```bash
uv run engineer loop --config project.json --cycles 3
uv run pytest
```

The mastering hypothesis runner that used to live here is now `mlab hyp run`
in [`ears/mlab`](../ears/mlab/), with H001–H006 under `ears/mlab/hypotheses/`.
