# Hammerspoon Development Harness — Plan Index

## Why this exists

A bug in `modules/tidy-music-workspace.lua` trusted the Hammerspoon docs, which said
`hs.execute`'s third return is a number. It is the string `"exit"` or `"signal"`. Error
output was going to `/dev/null`. The bug was invisible and took hours to trace.

This plan makes both failure modes structurally impossible and gives a coding agent a
machine-readable loop to verify its own Hammerspoon changes.

## Status

All six implementation phases are **not yet started**. The plan was written 2026-08-02.
The current code already works around the specific bug (line 50 of `tidy-music-workspace.lua`
checks the boolean `status`). This effort kills the *class* of bug, not the symptom.

## Confirmed decisions

- **Scope**: whole config, treated as the seed of an in-DAW macro suite. The music
  workspace is feature one; the layer split exists so features two, three, and beyond
  slot in without a rewrite.
- **Types in core/**: `lua-language-server` (LLS) annotations on plain Lua
  (`---@param` / `---@return` / `---@class`). No compile step, no generated files, no
  second language. The file you edit is the file that loads.
- **Git remote**: create private GitHub repo as `origin` before phase 0.
- **Worktree-per-change is deferred**: work on a `feature/harness` branch in the main
  checkout. Worktrees stay available for a large future change, but are not the routine
  workflow for this suite.
- **The e2e gate is deferred**: `harness/hsx e2e` launches Ableton and is slow and
  flaky. It stays a manual smoke test run deliberately, not part of `just verify`.
- **Dead code**: delete `snapshot.lua`, `spaces_util.lua`, `workspace_snapshot.json`, and
  the `snapshotPath` / `hotkeys.restore` keys in `config.lua`.
- **`hsx` CLI**: bash (~150 lines), not Rust/TS. The whole job is string-munging around
  one `hs -c` subprocess; JSON is produced inside Hammerspoon by `hs.json.encode`.

## Phases

| # | Document | One-line summary | Gate |
|---|----------|-----------------|------|
| 0 | [phase-0-tooling.md](phase-0-tooling.md) | Tooling, remote, feature branch | All tools install clean |
| 1 | [phase-1-logging.md](phase-1-logging.md) | Stop throwing away evidence | `.logs/hs.jsonl` readable after any run |
| 2 | [phase-2-contracts.md](phase-2-contracts.md) | Contract tests inside Hammerspoon | `hsx contracts` returns pass JSON |
| 3 | [phase-3-core.md](phase-3-core.md) | Extract pure logic to core/ (plain Lua) | `just test` green |
| 4 | [phase-4-boundary.md](phase-4-boundary.md) | Collapse effects into boundary/ | Leak guard passes |
| 5 | [phase-5-static.md](phase-5-static.md) | Linting + unit tests | `just check` and `just test` green |
| 6 | [phase-6-hsx.md](phase-6-hsx.md) | `hsx` CLI + glue rewrite + cleanup | `just verify` green |

## Verification command (final gate)

```
just verify   =   just check && just test && harness/hsx reload && harness/hsx contracts
```

`harness/hsx e2e` (launches Ableton) is a manual smoke test, run deliberately — it is
not part of the gate.

## Key files (current state, before refactor)

```
~/.hammerspoon/
  init.lua                           entry point (14 lines)
  config.lua                         music app, blocklist, hotkeys (21 lines)
  modules/tidy-music-workspace.lua   the only live feature (269 lines)
  modules/menubar.lua                menu bar icon (26 lines)
  modules/snapshot.lua               DEAD — delete in phase 6
  modules/spaces_util.lua            DEAD — delete in phase 6
  workspace_snapshot.json            DEAD — delete in phase 6
  scripts/task_name_prompt.applescript
  scripts/choose_als_file.applescript
```
