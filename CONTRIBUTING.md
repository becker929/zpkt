# Contributing

zpkt is the system I make my own tracks with, so it moves in whatever direction a track needs.
Bug reports and small fixes to `hands`, `ears` and `agent` are welcome. For anything larger,
open an issue first.

## Setup

```bash
make setup    # each core part's environment, and the Live Remote Script
make test     # hands, ears, mlab
```

Each part is its own uv project with its own lockfile. Run one part's tests from its folder:
`cd hands && uv run --all-extras pytest`.

## What a change needs

- **Tests that run offline.** Nothing in the suites talks to Live, reads a real project or
  needs audio files or models. `hands` tests use a fake Remote Script and fake GUI; `ears`
  tests synthesise their audio.
- **Contracts stay current.** The schemas in `lib/contracts/` are generated from each part's
  models (`hands/scripts/gen_schemas.py`, `ears/scripts/gen_schema.py`). A test fails if a
  committed schema is stale.
- **No personal paths.** What differs per Mac goes in `~/.config/zpkt/rig.toml`
  (`hands/src/hands/config.py`), not in code.
- **No audio, models, databases or `.als` files** in git, apart from the tiny synthetic fixtures
  already there.
- **A measure is calibrated before it is used.** New meters in `mlab` come with a known-answer
  check (`mlab calibrate`).

## Anything that touches Live

Try it on a copy of a set. Keep each LOM call short, and read
`agent/skills/ableton-guide/SKILL.md` first: most ways of crashing Live are already listed there.

Security reports: see [SECURITY.md](SECURITY.md).
