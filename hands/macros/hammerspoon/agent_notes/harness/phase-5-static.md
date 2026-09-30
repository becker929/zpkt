# Phase 5 — Static Checks and Unit Tests

Up: [index.md](index.md) | Back: [phase-4-boundary.md](phase-4-boundary.md) | Next: [phase-6-hsx.md](phase-6-hsx.md)

## Goal

`just check` exits zero on a clean tree and non-zero when a fault is introduced. `just test`
proves every pure-core decision with a busted spec that runs on plain Lua.

## Honest caveat — state this before relying on it

The language server does not flag comparing a string to a number. Lua allows it, so the
checker allows it. Static analysis would NOT have caught the original bug even with perfect
type information. Phase 2's contract test and Phase 4's named-table `{ ok, out, rawCode }`
return are what actually close that specific hole. Static checks catch a different class of
bugs (undefined fields, nil propagation, parameter mismatches) and are worth having for that.

## `luacheck` setup

Write `.luacheckrc`:

```lua
-- .luacheckrc
globals = { "hs", "spoon" }    -- Hammerspoon injects these at runtime
read_globals = { "utf8" }
max_line_length = 120
ignore = {
  "212",  -- unused argument (common in callback stubs)
}
```

Lint scope: `core`, `boundary`, `modules`, `init.lua`, `config.lua`, `contracts`. `core/`
is hand-written plain Lua, so luacheck lints it like any other file — there is no generated
code to exclude.

Add to `just check`:

```
luacheck core/ boundary/ modules/ init.lua config.lua contracts/
```

## `lua-language-server` setup

### `.luarc.json`

```json
{
  "runtime.version": "Lua 5.4",
  "workspace.library": [
    "/Applications/Hammerspoon.app/Contents/Resources/extensions"
  ],
  "diagnostics.libraryFiles": "Disable",
  "diagnostics.severity": {
    "assign-type-mismatch": "Warning",
    "param-type-mismatch": "Warning",
    "return-type-mismatch": "Warning",
    "undefined-field": "Warning",
    "need-check-nil": "Warning",
    "cast-local-type": "Warning"
  }
}
```

`workspace.library` points at the bundled HS extensions so `hs.*` is known, not flagged
as undefined. `diagnostics.libraryFiles: "Disable"` prevents LLS from emitting diagnostics
inside HS's own files (they lack full annotations and would be very noisy).

LLS is the single type authority for the whole tree. Because `core/` is annotated plain
Lua (phase 3), LLS type-checks it with the same `---@` annotations the editor reads — there
is no separate checker and no generated code to reconcile.

The six elevated diagnostics are the high-value ones:
- `undefined-field`: catches typos in `hs.` calls and in our own module APIs.
- `need-check-nil`: catches the `mainWindow()`-may-return-nil pattern this codebase is full of.
- `assign-type-mismatch`, `param-type-mismatch`, `return-type-mismatch`, `cast-local-type`:
  catch misuse of our own typed Lua.

### Invocation in `just check`

```
lua-language-server --check "$PWD" --checklevel=Warning --logpath="$PWD/.logs/lls"
```

`--check` takes the workspace root, not individual files. `--checklevel=Warning` makes any
diagnostic at Warning or higher cause a non-zero exit. The `check.json` written to `logpath`
contains the full finding list; useful for agents to read.

## `just check` recipe (full)

```
check:
    luacheck core/ boundary/ modules/ init.lua config.lua contracts/
    lua-language-server --check "$PWD" --checklevel=Warning --logpath="$PWD/.logs/lls"
    just leak-guard
```

There is no `build` step: `core/` is the loaded source, not a compiled artifact, so nothing
has to be regenerated or synced before linting runs.

## Busted unit tests

Specs live in `spec/`. Run with `busted spec/` — plain Lua 5.4, no Hammerspoon. The
`just test` recipe runs this.

### File list

- `spec/filename_spec.lua` — covers `core.filename`: `sanitize`, `timestampedName`,
  `copyPath`, `parseTaskPrompt`. At least 2 cases per function including edge cases (nil
  input, empty string, path with no `.als`, SKIP response).
- `spec/blocklist_spec.lua` — covers `core.blocklist`: `isMusicApp`, `isBlocklisted`. Test
  with empty list, matching entry, non-matching entry, multiple entries.
- `spec/geometry_spec.lua` — covers `core.geometry`: `pointInRect`. Test corners, center,
  strictly outside, edge cases (point exactly at boundary).
- `spec/log_spec.lua` — covers `core.log.record`: returns a table with expected fields
  (`ts`, `level`, `msg`). Fields argument is included. Nil fields omitted or nil.

### Representative spec (geometry)

```lua
-- spec/geometry_spec.lua
local geometry = require("core.geometry")

describe("geometry.pointInRect", function()
  local r = { x=10, y=20, w=100, h=50 }

  it("returns true for a point inside", function()
    assert.is_true(geometry.pointInRect(50, 40, r))
  end)
  it("returns true at the top-left corner (inclusive)", function()
    assert.is_true(geometry.pointInRect(10, 20, r))
  end)
  it("returns false at the right edge (exclusive)", function()
    assert.is_false(geometry.pointInRect(110, 40, r))
  end)
  it("returns false at the bottom edge (exclusive)", function()
    assert.is_false(geometry.pointInRect(50, 70, r))
  end)
  it("returns false for a point above", function()
    assert.is_false(geometry.pointInRect(50, 19, r))
  end)
  it("returns false for a point to the left", function()
    assert.is_false(geometry.pointInRect(9, 40, r))
  end)
end)
```

## Done when

- `just check` exits zero on the clean tree.
- Introducing a deliberate fault (e.g. `undefined_field_name` in a boundary file) makes
  `just check` exit non-zero with a message naming the fault.
- `just test` exits zero.
- Introducing a deliberate spec failure makes `just test` exit non-zero.
