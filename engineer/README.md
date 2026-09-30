# engineer

Decides what to try next and runs it. It uses the other three parts: it
asks `hands` to act, `ears` to measure and `taste` to judge.

| Module | What it does |
|---|---|
| `src/engineer/loop.py` | One cycle: `hands execute/record` → `ears analyze --json` → `taste` judge |
| `src/engineer/hypothesis.py` | Claim → variants → measured verdict, on `ears`' `mlab` meters |
| `src/engineer/search/` | Optimisers. `serum_evolver` and `ga_jsi` are autodaw's 2025 genetic algorithm and pairwise-preference code, kept for reference and not wired in yet |
| `hypotheses/` | Mastering hypotheses H001–H006, their template and results |

```bash
uv run engineer hyp run hypotheses/H004-low-mid-hole.yaml   # inputs from $MLAB_DATA (default ../ears/mlab)
uv run engineer loop --config project.json --cycles 3
uv run pytest
```

Hypothesis inputs such as renders live outside git. Point `MLAB_DATA` at the
lab's data folder (for example `~/Music/hw002-mastering-lab`) to use them.
