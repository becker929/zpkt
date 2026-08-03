# Phase 6 — `hsx` CLI, Module Rewrite, and Cleanup

Up: [index.md](index.md) | Back: [phase-5-static.md](phase-5-static.md)

## Goal

After this phase an agent can change a module, run one command, and get a machine-readable
verdict with no human present. The module glue is rewritten as thin orchestration over
`core/` and `boundary/`. Dead code is deleted. The skill doc is corrected.

## The `hsx` CLI tool

`harness/hsx` is a bash script (~150 lines). It wraps `hs -c` and always returns JSON on
stdout plus a meaningful exit code. Nothing returns prose.

Why bash and not Rust/TS (the global preference for programs): `hsx` is a shell adapter.
Its entire job is to build a `hs -c` command string, capture stdout, strip Hammerspoon's
noisy preamble, and pass JSON through. The JSON is produced inside Hammerspoon by
`hs.json.encode`. A compiled binary would need a build/install step and would still shell
out to `hs` — adding a toolchain to what is fundamentally string-munging around one
subprocess. Bash is dependency-free and matches the "thin wrapper" reality.

### Sentinel pattern (core trick)

Hammerspoon's stdout is noisy: `-- Loading extension: ipc` preamble lines, any `print()`
output from loaded modules, and finally the returned value. Isolate the result with a
sentinel prefix so `grep` finds it regardless of line position:

```bash
wrap_eval() {
  local lua="$1"
  # Build an expression that emits a sentinel-prefixed JSON envelope.
  cat <<LUA
local ok, res = pcall(function() return $lua end)
print('__HSX__' .. hs.json.encode({ ok=ok, result=ok and res or tostring(res) }))
LUA
}

run_hs() {
  local lua="$1"
  /opt/homebrew/bin/hs -c "$(wrap_eval "$lua")" 2>&1 \
    | grep '^__HSX__' | sed 's/^__HSX__//' | tail -1
}
```

The result is always a `{ "ok": true/false, "result": ... }` JSON object. A Lua runtime
error becomes `{ "ok": false, "result": "<error string>" }` rather than a non-zero `hs`
exit with garbage output.

**IPC print-crash note:** the `print('__HSX__'...)` in the eval wrapper is synchronous —
it runs before `hs -c` returns — so it does not trigger the IPC socket-closed crash.
Async `print()` in timers/watchers/eventtaps would crash; we never do that.

### Commands

```bash
#!/usr/bin/env bash
set -euo pipefail
HS=/opt/homebrew/bin/hs
LOGS=~/.hammerspoon/.logs/hs.jsonl

usage() { echo "usage: hsx <reload|eval|contracts|invoke|state|logs|shot|e2e>"; exit 1; }

case "${1:-}" in
  reload)
    # Reload config and report load errors.
    result="$(run_hs 'hs.reload(); return "reloading"')"
    echo "$result"
    # Wait for reload to complete (hs.reload() is async).
    sleep 1
    # Check for errors in the log.
    errors="$(tail -20 "$LOGS" 2>/dev/null | jq -s '[.[] | select(.level == "error")]' 2>/dev/null || echo "[]")"
    jq -n --argjson errors "$errors" '{ ok: ($errors | length == 0), errors: $errors }'
    ;;

  eval)
    # Evaluate a Lua expression inside HS. Returns JSON { ok, result }.
    [[ -z "${2:-}" ]] && { echo '{"ok":false,"result":"usage: hsx eval <lua>"}'; exit 1; }
    run_hs "$2"
    ;;

  contracts)
    # Run all contracts/*_contract.lua inside HS. Returns JSON { passed, failed, results }.
    result="$(run_hs "require('contracts.runner').run()")"
    echo "$result"
    # Exit non-zero if any contract failed.
    failed="$(echo "$result" | jq -r '.failed // 1')"
    [[ "$failed" == "0" ]]
    ;;

  invoke)
    # Call a module function: hsx invoke <mod> <fn> [args-json]
    # Optional --fixture flag: swaps boundary/ stubs (not yet implemented; see note).
    [[ -z "${2:-}" || -z "${3:-}" ]] && { echo '{"ok":false,"result":"usage: hsx invoke <mod> <fn> [args-json]"}'; exit 1; }
    mod="$2" fn="$3" args="${4:-nil}"
    run_hs "return require('$mod')['$fn']($args)"
    ;;

  state)
    # Return current workspace state as JSON: focused app, window frames.
    run_hs "
      local wins = {}
      for _, w in ipairs(hs.window.allWindows()) do
        local app = w:application()
        local f = w:frame()
        wins[#wins+1] = {
          id=w:id(), title=w:title(),
          appName=app and app:name() or nil,
          bundleID=app and app:bundleID() or nil,
          frame={x=f.x,y=f.y,w=f.w,h=f.h},
          minimized=w:isMinimized(),
          focused=(w==hs.window.focusedWindow()),
        }
      end
      local fa = hs.application.frontmostApplication()
      return { focusedApp=fa and fa:bundleID() or nil, windows=wins }
    "
    ;;

  logs)
    # Tail the structured log (pure shell, no HS).
    n="${2:-20}"
    tail -"$n" "$LOGS" 2>/dev/null | jq -s '.' || echo "[]"
    ;;

  shot)
    # Take a screenshot, write to a temp file, print the path.
    run_hs "
      local path = os.tmpname() .. '.png'
      hs.screen.mainScreen():snapshot():saveToFile(path)
      return path
    "
    ;;

  e2e)
    # Minimal end-to-end: invoke M.activate() and assert Ableton is frontmost.
    # NOTE: this WILL launch Ableton Live. It is a manual smoke test, run deliberately.
    # It is deferred out of `just verify` — slow and flaky, not a gate.
    run_hs "require('modules.tidy-music-workspace').activate(); return 'activating'"
    sleep 5
    hsx state | jq -e '.focusedApp == "com.ableton.live"' \
      && echo '{"ok":true}' \
      || { echo '{"ok":false,"detail":"Ableton not frontmost after 5s"}'; exit 1; }
    ;;

  *) usage ;;
esac
```

`chmod +x harness/hsx` so it runs directly. Invoke as `harness/hsx <cmd>` from the repo
root, or add `harness/` to PATH.

## Rewrite `modules/tidy-music-workspace.lua` as glue

The rewritten module orchestrates: ask boundary for state, call core to decide, hand
decision back to boundary. No `hs.*` primitive appears here. The two public functions keep
their names and signatures.

```lua
-- modules/tidy-music-workspace.lua (glue only after phase 6)
local filename    = require("core.filename")
local applescript = require("boundary.applescript")
local apps        = require("boundary.apps")
local window      = require("boundary.window")
local screen      = require("boundary.screen")
local keyboard    = require("boundary.keyboard")
local shell       = require("boundary.shell")
local notify      = require("boundary.notify")
local clock       = require("boundary.clock")
local log         = require("boundary.log")
local config      = require("config")

local M = {}

-- Module-local, defined before M.activate so no forward declaration is needed.
local function _prepareAndLaunch()
  local count = apps.prepareWorkspace()
  if count > 0 then notify.show("Hiding " .. count .. " apps…") end
  window.launchAndResize(screen.underMouse())
end

function M.activate()
  log.info("activate: starting")

  -- Auto-save if the music app is already running.
  local app = apps.musicApp()
  if app then
    local raw = applescript.run("task_name_prompt")
    local taskName, skipped = filename.parseTaskPrompt(raw)
    if not skipped then
      local part  = filename.sanitize(taskName)
      local stamp = clock.stamp()
      local fname = filename.timestampedName(stamp, part)
      keyboard.saveAs(app, fname, function()
        log.info("activate: save complete, continuing")
        _prepareAndLaunch()
      end)
      return
    end
  end
  _prepareAndLaunch()
end

function M.openProjectCopy()
  log.info("openProjectCopy: starting")
  local src = applescript.run("choose_als_file")
  if not src then return end

  local dst = filename.copyPath(src, clock.stamp())

  local ok, err = shell.copyFile(src, dst)
  if not ok then
    log.warn("openProjectCopy: copy failed", { err=err })
    notify.show("Music Workspace: could not copy project")
    return
  end

  local count = apps.prepareWorkspace()
  if count > 0 then notify.show("Hiding " .. count .. " apps…") end
  notify.show("Opening copy…")
  shell.openWithBundle(config.musicApp.bundleID, dst)
  window.launchAndResize(screen.underMouse())
end

return M
```

The music-app handle from `apps.musicApp()` is passed straight back into `keyboard.saveAs`
(a boundary call). The glue holds the handle but never calls `hs.` on it — app lookup lives
in `boundary/apps.lua`, and the timestamp comes from `boundary/clock.lua`. No `hs.*` and no
`os.date` appear in this file, which is what the leak guard checks.

## Delete dead code

On the `feature/harness` branch, remove these files and the config keys that reference them:

- `modules/snapshot.lua` — delete.
- `modules/spaces_util.lua` — delete.
- `workspace_snapshot.json` — delete.
- `config.lua` — remove `snapshotPath` key and `hotkeys.restore` key.

## Update the `hammerspoon` skill doc

The skill doc at `~/.claude/skills/hammerspoon/` currently references:
- `modules/workspace.lua` (does not exist — was deleted in T001).
- `workspace.activate()` and `workspace.restore()` (restore no longer exists).
- An outdated file structure that includes snapshot/spaces_util.

Update the skill to reflect the new layer structure: `core/`, `boundary/`, `modules/`
(glue only), the `hsx` CLI, the `contracts/` runner, and the `just verify` gate. Remove all
references to snapshot, spaces_util, and restore.

## `just verify` (full gate)

```
verify: check test
    harness/hsx reload
    just contracts
```

The gate is static checks, unit tests, a clean reload, and contracts. It does not launch
Ableton. `harness/hsx e2e` is deferred out of the gate: run it by hand as a smoke test when
you want a full activate-and-observe pass. The gate stays fast and deterministic so an agent
can run it after every change.

Two rules for every agent using this:

**Assert on structured state, not screenshots.** `hsx state` gives exact window frames,
bundle IDs, and which app is focused as machine-readable data. That is what a test asserts
against. For the music workspace the assertion is: `focusedApp == "com.ableton.live"` and
the frame equals the expected rectangle. Screenshots from `hsx shot` are evidence attached
to a report, not the basis of pass/fail.

**Never suppress output to make a run look clean.** If a check is noisy, fix the check.
The leak guard exists to make suppression fail the build.

## Done when

- `harness/hsx contracts` returns `{ "passed": N, "failed": 0 }`.
- `harness/hsx state` returns a valid JSON window snapshot.
- `just verify` exits zero (static + tests + reload + contracts; no Ableton launch).
- `harness/hsx e2e` passes when run manually — the deferred smoke test, not part of the gate.
- `modules/tidy-music-workspace.lua` reaches no `hs.*` and no `os.date` directly —
  enforced by `just leak-guard`, not just asserted. App lookup goes through
  `boundary/apps.lua`; the timestamp goes through `boundary/clock.lua`.
- Dead files are deleted and `config.lua` has no snapshot/restore keys.
- The hammerspoon skill doc is current.
- The feature branch is pushed to `origin` and a PR is open.
- CI (if any — none configured yet; `just verify` is the gate) is green.
