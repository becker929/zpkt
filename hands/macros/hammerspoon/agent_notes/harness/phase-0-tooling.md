# Phase 0 — Tooling, Remote, Feature Branch

Up: [index.md](index.md) | Next: [phase-1-logging.md](phase-1-logging.md)

## Goal

A working git remote, a `feature/harness` branch, and all CLI tools installed. Nothing
else in the plan works without this foundation.

## Steps

### 1. Create private GitHub remote

`gh` is authenticated. Run from the repo root:

```bash
gh repo create hammerspoon-config --private --source . --remote origin --push
```

Verify: `git remote -v` shows `origin` pointing to the new repo. Push should have sent
`main` with its one existing commit (`451172f`).

### 2. Create the feature branch

Work on a branch in the main checkout. Worktree-per-change is deferred: it stays available
for a large future change, but is not the routine workflow for this suite.

```bash
git checkout -b feature/harness
```

All remaining phases execute on `feature/harness`. Open a PR and merge to `main` when
`just verify` is green.

### 3. Write `justfile`

Create `~/.hammerspoon/justfile` (on the `feature/harness` branch). Full content:

```justfile
set shell := ["bash", "-uc"]

# One-time tooling install — idempotent
setup:
    brew install lua-language-server || true
    luarocks install --lua-version 5.4 busted || true
    luarocks install --lua-version 5.4 luacheck || true

# Static checks: lint + language server + boundary leak guard
# core/ is hand-written Lua with LLS annotations — linted and type-checked like everything else.
check:
    luacheck core boundary modules init.lua config.lua contracts
    lua-language-server --check "$PWD" --checklevel=Warning --logpath="$PWD/.logs/lls"
    just leak-guard

# Unit tests for pure core (busted; runs on plain Lua, no Hammerspoon)
test:
    busted spec/

# Contract tests inside Hammerspoon
contracts:
    harness/hsx contracts

# Full gate: static + unit + reload + contracts
# e2e is deferred: `harness/hsx e2e` launches Ableton — run it manually as a smoke test.
verify: check test
    harness/hsx reload
    just contracts

# Fails if effects leak out of boundary/ (three structural rules, see below)
leak-guard:
    #!/usr/bin/env bash
    set -euo pipefail
    # Rule A: shell/exec primitives may live only in boundary/.
    if rg -n --glob '*.lua' \
          -e 'hs\.execute\s*\(' \
          -e 'io\.popen\s*\(' \
          -e 'os\.execute\s*\(' \
          core/ modules/ init.lua config.lua 2>/dev/null; then
      echo "LEAK: shell/exec primitive found outside boundary/" >&2
      exit 1
    fi
    # Rule B: core/ is pure — no hs.* and no wall-clock read.
    if rg -n --glob '*.lua' -e 'hs\.' -e 'os\.date' -e 'os\.time' core/ 2>/dev/null; then
      echo "LEAK: core/ is not pure (hs.* or wall-clock effect found)" >&2
      exit 1
    fi
    # Rule C: the feature glue orchestrates core/ + boundary/ and touches no hs.* itself.
    if rg -n -e 'hs\.' modules/tidy-music-workspace.lua 2>/dev/null; then
      echo "LEAK: glue module reaches hs.* directly — route it through boundary/" >&2
      exit 1
    fi
    echo "leak-guard: clean"
```

Rule C names the one feature glue file rather than all of `modules/`. `init.lua` is the
composition root (it binds hotkeys with `hs.hotkey`), and `modules/menubar.lua` is a thin
effectful UI shell (`hs.menubar`, `hs.eventtap`) — both legitimately touch `hs.*`, so
neither is held to the glue-purity rule. As the suite grows, each new feature glue file gets
added to Rule C's file list; `menubar.lua` is a candidate to move under `boundary/` later,
which would let Rule C widen to all of `modules/`.

### 4. Write `.gitignore`

```
.logs/
*.tmp
.worktrees/
```

### 5. Install tooling

Run from the repo root, on the `feature/harness` branch:

```bash
just setup 2>&1 | tee ~/logs/hs-setup.log
```

There is no Teal toolchain to install — `core/` is plain Lua. Types come from LLS
annotations, which need no compiler.

### 6. Create directory scaffolding

Create the directories so `require` paths resolve cleanly later:
`core/`, `boundary/`, `spec/`, `contracts/`, `harness/`, `.logs/`.

There is no `types/` directory: `core/` references zero `hs.*`, so there are no external
types to declare. Type info for `hs.*` in `boundary/` comes from the LLS
`workspace.library` setting configured in phase 5, not from hand-written stubs.

## Done when

- `git remote -v` shows `origin`.
- `busted --version`, `luacheck --version`, `lua-language-server --version` all succeed.
- `git branch` shows `feature/harness` checked out.
- `.gitignore` committed.
- `justfile` committed.

## What does NOT happen in this phase

No Lua is written. No Hammerspoon changes. The goal is a green setup foundation only.
