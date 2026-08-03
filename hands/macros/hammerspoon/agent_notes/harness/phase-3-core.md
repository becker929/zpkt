# Phase 3 — Extract Pure Logic to `core/` (plain Lua + LLS annotations)

Up: [index.md](index.md) | Back: [phase-2-contracts.md](phase-2-contracts.md) | Next: [phase-4-boundary.md](phase-4-boundary.md)

## Goal

Every decision the config makes lives in `core/` as plain Lua with LLS type annotations and
no `hs.*` dependency. `core/*.lua` can be loaded and tested on a plain Lua interpreter in
milliseconds. The layer split is structural: if something needs `hs.`, it does not belong here.

As the suite grows, `core/` is where the reusable macro logic accumulates — filename rules,
selection rules, geometry math — each function pure, each covered by a busted spec.

## Why plain Lua, not a compiler

The file you edit is the file Hammerspoon loads. There is no `.tl` source, no generated
`.lua`, no `just build`, and no "did you rebuild?" sync guard. Types come from
`lua-language-server` (LLS) annotations — `---@param`, `---@return`, `---@class` — which LLS
reads directly. Phase 5 wires LLS into `just check`, so a type error fails the gate without
any build step in between.

The functions in `core/` are small and string-shaped; annotations give the editor and the
gate real type-checking with none of a second-language toolchain's cost.

## Files to create

### `core/filename.lua`

Handles all filename derivation. Takes timestamps and strings as arguments — never calls
`os.date` (that is an effect; the caller passes the result in).

```lua
local M = {}

--- Strips unsafe filename characters, collapses repeated underscores,
--- trims leading/trailing underscores.
---@param s string
---@return string
function M.sanitize(s)
  -- Wrapped in parens so only the string is returned, not gsub's match count.
  return (s:gsub("[^%w%-]", "_"):gsub("_+", "_"):gsub("^_", ""):gsub("_$", ""))
end

--- Builds a timestamped filename part: "20260802_143000" or "20260802_143000_task_name".
---@param stamp string  result of os.date("%Y%m%d_%H%M%S"), passed in by the caller
---@param part string   already-sanitized task name, or "" for no suffix
---@return string
function M.timestampedName(stamp, part)
  if part == "" then return stamp end
  return stamp .. "_" .. part
end

--- Derives the destination path for an .als copy.
---@param src string    "/path/to/project.als"
---@param stamp string  result of os.date("%Y%m%d_%H%M%S")
---@return string       "/path/to/project_copy_20260802_143000.als"
function M.copyPath(src, stamp)
  local dir  = src:match("^(.+)/[^/]+$") or "."
  local name = src:match("/([^/]+)%.als$") or "project"
  return dir .. "/" .. name .. "_copy_" .. stamp .. ".als"
end

--- Parses the AppleScript dialog result from task_name_prompt.applescript.
--- skipped is true if the user clicked Skip or the input is empty/nil.
--- taskName is "" when skipped.
---@param raw string|nil
---@return string   taskName
---@return boolean  skipped
function M.parseTaskPrompt(raw)
  if not raw or raw == "SKIP" then return "", true end
  local name = raw:match("^SAVE:(.*)")
  if not name then return "", true end
  return name, false
end

return M
```

### `core/blocklist.lua`

```lua
---@class Entry
---@field name string
---@field bundleID string

local M = {}

--- Returns true if bundleID matches the music app's bundle ID.
---@param bundleID string
---@param musicBundleID string
---@return boolean
function M.isMusicApp(bundleID, musicBundleID)
  return bundleID == musicBundleID
end

--- Returns true if bundleID is in the blocklist.
---@param bundleID string
---@param blocklist Entry[]
---@return boolean
function M.isBlocklisted(bundleID, blocklist)
  for _, entry in ipairs(blocklist) do
    if entry.bundleID == bundleID then return true end
  end
  return false
end

return M
```

### `core/geometry.lua`

```lua
---@class Rect
---@field x number
---@field y number
---@field w number
---@field h number

local M = {}

--- Returns true if the point (x, y) lies inside the rectangle
--- (inclusive of the top-left edge, exclusive of the bottom-right edge).
---@param x number
---@param y number
---@param r Rect
---@return boolean
function M.pointInRect(x, y, r)
  return x >= r.x and x < r.x + r.w and y >= r.y and y < r.y + r.h
end

return M
```

### `core/log.lua`

See phase 1. The formatter returns a plain table; `boundary/log.lua` encodes and writes it.

## No `types/` directory

`core/` references zero `hs.*`, so there are no external types to declare. Type info for
`hs.*` — needed only in `boundary/` — comes from the LLS `workspace.library` setting
configured in phase 5, which points at Hammerspoon's bundled extension annotations. There
are no hand-written stub files to keep in sync.

The rule that pairs an assumption with a contract still holds, but it lives in phase 2: every
`hs.*` behavior a boundary file relies on gets a matching file in `contracts/`.

## Busted specs

Write `spec/filename_spec.lua`, `spec/blocklist_spec.lua`, `spec/geometry_spec.lua` to
verify every function. These run on plain Lua 5.4 with no Hammerspoon running, and require
the `core/*.lua` files directly.

```lua
-- spec/filename_spec.lua (representative excerpt)
local filename = require("core.filename")

describe("filename.sanitize", function()
  it("strips spaces", function()
    assert.equals("hello_world", filename.sanitize("hello world"))
  end)
  it("collapses repeated underscores", function()
    assert.equals("a_b", filename.sanitize("a__b"))
  end)
  it("trims leading and trailing underscores", function()
    assert.equals("hello", filename.sanitize("_hello_"))
  end)
end)

describe("filename.parseTaskPrompt", function()
  it("parses a SAVE: response", function()
    local name, skipped = filename.parseTaskPrompt("SAVE:my task")
    assert.equals("my task", name)
    assert.is_false(skipped)
  end)
  it("treats SKIP as skipped", function()
    local _, skipped = filename.parseTaskPrompt("SKIP")
    assert.is_true(skipped)
  end)
  it("treats nil as skipped", function()
    local _, skipped = filename.parseTaskPrompt(nil)
    assert.is_true(skipped)
  end)
end)
```

## Done when

- `just test` (busted on `spec/`) is green.
- `core/` contains zero `hs.*` references (the leak guard, wired into `just check` in
  phase 5, enforces this).
- `lua-language-server --check` reports no diagnostics on `core/` (the annotations are
  valid and internally consistent), and `luacheck core` is clean.
