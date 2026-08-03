# Phase 1 — Stop Throwing Away Evidence

Up: [index.md](index.md) | Back: [phase-0-tooling.md](phase-0-tooling.md) | Next: [phase-2-contracts.md](phase-2-contracts.md)

## Goal

Every module run leaves a readable trace on disk. The moment something goes wrong, the
answer is in `.logs/hs.jsonl` without a human reading Hammerspoon's console.

This phase has no structural refactor — it adds the logging helper and removes the one
remaining ignored return value, nothing else.

## What the logging helper looks like

The formatter is pure (no `hs.*`), so it lives in `core/` and is testable. The writer
does file IO, so it lives in `boundary/`.

### `core/log.lua` (plain Lua + LLS annotations — the formatter)

```lua
local M = {}

--- Builds a structured log record as a plain table.
--- The caller (boundary) encodes to JSON and writes to disk.
---@param level string  "debug" | "info" | "warn" | "error"
---@param msg string    human-readable description
---@param fields table<string, any>|nil  extra context (may be nil)
---@param ts integer    os.time() passed in by the caller (keeps this pure)
---@return table<string, any>
function M.record(level, msg, fields, ts)
  return {
    ts     = ts,
    level  = level,
    module = fields and fields.module or nil,
    msg    = msg,
    fields = fields,
  }
end

return M
```

This is the file that loads — there is no compile step. LLS reads the `---@` annotations
directly for type-checking in phase 5.

### `boundary/log.lua` (effectful writer)

```lua
local logCore = require("core.log")

local M = {}
local PATH = hs.configdir .. "/.logs/hs.jsonl"

function M.write(level, msg, fields)
  local rec = logCore.record(level, msg, fields, os.time())
  local ok, encoded = pcall(hs.json.encode, rec)
  if not ok then return end
  local f = io.open(PATH, "a")
  if not f then return end
  f:write(encoded .. "\n")
  f:close()   -- close == flush; crash-safe
end

function M.debug(msg, fields) M.write("debug", msg, fields) end
function M.info(msg, fields)  M.write("info",  msg, fields) end
function M.warn(msg, fields)  M.write("warn",  msg, fields) end
function M.error(msg, fields) M.write("error", msg, fields) end

return M
```

`f:close()` on every write is deliberate: if Hammerspoon crashes the log is still readable.

**IPC caveat (must not be broken):** `boundary/log.lua` uses `io.open` (file IO), not
`print`. This makes it safe inside timer/watcher/eventtap callbacks, unlike `print()`,
which can crash Hammerspoon when `hs.ipc` is active and the IPC socket is already closed.
The whole codebase rule: never `print()` in async callbacks. Use `hs.alert.show` for
user-facing feedback or `boundary/log.lua` for machine-readable traces.

## What changes in `tidy-music-workspace.lua`

Only one thing: line 265 ignores the return of `hs.execute("open -b ...")`. Log it.

```lua
-- Before (line 265):
hs.execute(string.format("open -b %q %q", config.musicApp.bundleID, dst))

-- After:
local res = { out, ok = hs.execute(string.format("open -b %q %q", config.musicApp.bundleID, dst) .. " 2>&1") }
if not res.ok then
  log.warn("openProjectCopy: open failed", { out = res.out })
end
```

Replace the existing `log = hs.logger.new(...)` usage with `boundary/log.lua` throughout
this module. The `hs.logger` lines can be removed.

## No other changes

Do not refactor the module structure in this phase. The layer split happens in phases 3–4.
This phase is only about evidence.

## Done when

Running `workspace.activate()` via the menu bar icon leaves a readable `.logs/hs.jsonl`
with timestamped entries showing what the module tried and what came back. Verify with:

```bash
harness/hsx logs 20
```

(Phase 6 writes `hsx` — for now, `tail -20 ~/.hammerspoon/.logs/hs.jsonl` is acceptable.)
