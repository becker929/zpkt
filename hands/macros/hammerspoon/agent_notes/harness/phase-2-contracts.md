# Phase 2 — Contract Tests (the Must-Ship Phase)

Up: [index.md](index.md) | Back: [phase-1-logging.md](phase-1-logging.md) | Next: [phase-3-core.md](phase-3-core.md)

## Goal

A contract test runs inside Hammerspoon and asserts what an `hs.*` API actually does, as
opposed to what its documentation claims. It does not test our code. It tests our
assumptions. When Hammerspoon or macOS changes underneath us, this fails loudly with a
message naming the assumption that broke — instead of a feature silently corrupting.

**This is the phase that would have caught the original bug.** The bug trusted the docs.
A contract test would have pinned the real behavior and failed the moment the assumption
was about to be used.

## The runner

`contracts/runner.lua` (plain Lua — runs inside Hammerspoon, with the full `hs.*` API
available).

It auto-discovers every `contracts/*_contract.lua`, each of which returns
`function(t) ... end`. The `t` table provides assertions. The runner collects results and
returns an already-encoded JSON string.

```lua
-- contracts/runner.lua
local M = {}

local function newT(results, suite)
  local function record(ok, msg, detail)
    results[#results+1] = { suite=suite, ok=ok, msg=msg, detail=detail }
  end
  return {
    eq = function(got, want, msg)
      local pass = (got == want)
      record(pass, msg or "eq",
        pass and nil or ("expected "..tostring(want).." got "..tostring(got)))
    end,
    isType = function(got, want, msg)
      local pass = (type(got) == want)
      record(pass, msg or "isType",
        pass and nil or ("expected type "..want.." got "..type(got)))
    end,
    ok = function(val, msg)
      record(val and true or false, msg or "ok",
        val and nil or "expected truthy")
    end,
  }
end

function M.run()
  local dir = hs.configdir .. "/contracts"
  local results = {}

  for file in hs.fs.dir(dir) do
    local suite = file:match("^(.+)_contract%.lua$")
    if suite then
      local modname = "contracts." .. suite .. "_contract"
      local ok, mod = pcall(require, modname)
      if not ok then
        results[#results+1] = { suite=suite, ok=false, msg="load", detail=tostring(mod) }
      else
        local t = newT(results, suite)
        local runok, err = pcall(mod, t)
        if not runok then
          results[#results+1] = { suite=suite, ok=false, msg="crash", detail=tostring(err) }
        end
      end
    end
  end

  local passed, failed = 0, 0
  for _, r in ipairs(results) do
    if r.ok then passed = passed + 1 else failed = failed + 1 end
  end
  return hs.json.encode({ passed=passed, failed=failed, results=results })
end

return M
```

## Contract files to write

Write one per `hs.*` API that a boundary file will depend on. Start with the APIs used in
the current `tidy-music-workspace.lua`.

### `contracts/execute_contract.lua` — the original bug, pinned as a test

```lua
-- Pins the REAL behavior of hs.execute vs what the docs claim.
-- The original 2026 bug: code compared the 3rd return to 0 (a number).
-- The 3rd return is actually the string "exit" or "signal".
return function(t)
  local out, ok, kind, code = hs.execute("exit 3")
  t.eq(ok, false, "non-zero exit -> 2nd return is false")
  t.isType(kind, "string", "3rd return is a STRING, not a number (docs are wrong)")
  t.eq(kind, "exit", "3rd return is 'exit' for a normal process exit")
  t.isType(code, "number", "4th return is the numeric exit code")
  t.eq(code, 3, "4th return equals the exit code value")

  local _, ok2, kind2, code2 = hs.execute("true")
  t.eq(ok2, true, "exit 0 -> 2nd return is true")
  t.eq(kind2, "exit", "successful command also reports 'exit'")
  t.eq(code2, 0, "successful command exit code is 0")
end
```

### `contracts/osascript_contract.lua` — AppleScript via hs.execute

```lua
-- Pins hs.execute behavior for an osascript call.
return function(t)
  local out, ok = hs.execute('osascript -e "return 42"')
  t.eq(ok, true, "osascript exit 0 -> ok is true")
  t.isType(out, "string", "stdout is a string")
  t.ok(out:match("42"), "stdout contains the returned value")
end
```

### `contracts/screen_contract.lua` — hs.screen.frame() excludes menu bar

```lua
-- Confirms frame() excludes menu bar / Dock (the value we use for resize target).
return function(t)
  local main = hs.screen.mainScreen()
  t.ok(main, "mainScreen() returns a screen")
  local f = main:frame()
  local ff = main:fullFrame()
  t.ok(f.h < ff.h or f.y > ff.y, "frame() is smaller/offset vs fullFrame()")
end
```

Add more contracts as boundary files are written in phase 4 — one contract per API assumption.

## Running contract tests before `hsx` exists

The `hsx` tool is written in phase 6. For phases 2–5, run contracts directly:

```bash
/opt/homebrew/bin/hs -c 'print(require("contracts.runner").run())' 2>&1 | grep -v '^--' | tail -1 | jq .
```

The `grep -v '^--'` strips the Hammerspoon extension-loading preamble. `tail -1` gets the
last output line (the JSON). `jq .` pretty-prints it.

## Done when

- `contracts/runner.lua` and at least `contracts/execute_contract.lua` exist.
- Running the command above returns `{"passed":N,"failed":0,"results":[...]}`.
- Deliberately changing the assertion in `execute_contract.lua` (e.g. asserting
  `kind == "number"`) produces `"failed":1` with a message identifying the broken assertion.
- A new Hammerspoon version that changes API behavior would surface here before any module
  breaks.
