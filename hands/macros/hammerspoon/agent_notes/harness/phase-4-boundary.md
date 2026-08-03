# Phase 4 — Collapse Effects into `boundary/`

Up: [index.md](index.md) | Back: [phase-3-core.md](phase-3-core.md) | Next: [phase-5-static.md](phase-5-static.md)

## Goal

Every `hs.*` primitive, shell call, file IO, and AppleScript invocation lives in exactly
one thin file under `boundary/`. No other file may cause effects. After this phase the leak
guard passes on the whole codebase, and the module glue in `modules/` reads like a paragraph
calling `core/` and `boundary/` by name.

## The core rule, concretely

`boundary/shell.lua` is the only file allowed to call `hs.execute`, `io.popen`, or
`os.execute`. It always keeps stderr (`2>&1`) and returns a named table:

```lua
--- @class ShResult
--- @field ok boolean   true only when the command exited with code 0
--- @field out string   combined stdout and stderr
--- @field rawCode any  UNTRUSTED — the 3rd return of hs.execute is the string "exit"
---                     or "signal", NOT a number. Never compare to a number. Use `ok`.
```

Callers can only write `if not result.ok then` — the mistake from the original bug is no
longer a natural thing to type. If someone typos the field name the language server flags it.

## One boundary file per effect, created when a feature needs it

The rule is one thin file per kind of effect. This phase creates the files the music
workspace feature actually exercises: shell, AppleScript, screen geometry, app lookup and
control, window control, keystroke synthesis, user notifications, and the wall clock. That
is the ceiling for feature one, not a guess about the future.

Two of these exist so the glue never reaches for an effect directly. `apps.musicApp()`
owns the `hs.application.get`/`find` lookup, and `clock.stamp()` owns the one `os.date`
call. With those in place the feature glue in phase 6 contains no `hs.*` and no wall-clock
read — a property the leak guard enforces.

Later suite features add new boundary files as they reach for new effects — a `boundary/midi.lua`
when a macro touches MIDI, a `boundary/osc.lua` for OSC, and so on. Do not create empty
boundary files ahead of a feature that uses them. The leak guard is what keeps the discipline
honest: any new effect written outside `boundary/` fails the gate, which forces the new file
into existence at the moment it is actually needed.

## Files to create

### `boundary/shell.lua`

```lua
local log = require("boundary.log")
local M = {}

--- Runs a shell command. Always captures stderr.
--- Returns ShResult: { ok, out, rawCode }
--- NEVER read rawCode to decide success — always use ok.
function M.run(cmd)
  local out, ok, rawCode = hs.execute(cmd .. " 2>&1")
  local result = { ok = (ok == true), out = out or "", rawCode = rawCode }
  log.debug("shell.run", { cmd=cmd, ok=result.ok, rawCode=rawCode })
  return result
end

--- Copies src to dst. Returns (true, nil) or (nil, errMsg).
function M.copyFile(src, dst)
  local r = M.run(string.format("cp %q %q", src, dst))
  if not r.ok then
    return nil, "cp failed: " .. r.out
  end
  return true, nil
end

--- Opens a file with the given app bundle ID.
function M.openWithBundle(bundleID, path)
  local r = M.run(string.format("open -b %q %q", bundleID, path))
  if not r.ok then
    log.warn("shell.openWithBundle failed", { bundleID=bundleID, path=path, out=r.out })
  end
  return r.ok
end

return M
```

### `boundary/applescript.lua`

The only file allowed to run AppleScript. `runScript` from `tidy-music-workspace.lua` moves
here unchanged in behavior.

```lua
local shell = require("boundary.shell")
local M = {}

--- Runs a checked-in AppleScript from ~/.hammerspoon/scripts/<name>.applescript.
--- Returns trimmed stdout on success, or nil if cancelled / errored.
function M.run(name)
  local path = hs.configdir .. "/scripts/" .. name .. ".applescript"
  local r = shell.run('osascript "' .. path .. '"')
  if not r.ok then return nil end
  return r.out:gsub("%s+$", "")
end

return M
```

### `boundary/screen.lua`

```lua
local geometry = require("core.geometry")
local M = {}

--- Returns the frame of the screen the mouse pointer is on.
--- Falls back to mainScreen. Uses core.geometry.pointInRect for the pure test.
function M.underMouse()
  local pos = hs.mouse.absolutePosition()
  for _, screen in ipairs(hs.screen.allScreens()) do
    local f = screen:frame()
    if geometry.pointInRect(pos.x, pos.y, f) then
      return f
    end
  end
  return hs.screen.mainScreen():frame()
end

return M
```

### `boundary/apps.lua`

```lua
local blocklist = require("core.blocklist")
local log       = require("boundary.log")
local config    = require("config")
local M = {}

--- Returns the running music app handle, or nil if it is not running.
--- The only place the music-app lookup lives, so the glue never calls hs.application.*.
---@return hs.application|nil
function M.musicApp()
  return hs.application.get(config.musicApp.bundleID)
      or hs.application.find(config.musicApp.name)
end

--- Quits blocklisted apps and hides all non-music visible apps.
--- Returns the number of apps hidden.
function M.prepareWorkspace()
  for _, entry in ipairs(config.blocklist) do
    local app = hs.application.get(entry.bundleID)
             or hs.application.find(entry.name)
    if app then
      log.info("killing blocklisted app", { name=entry.name })
      app:kill()
    end
  end

  local toHide = {}
  for _, win in ipairs(hs.window.allWindows()) do
    local app = win:application()
    if app then
      local bid = app:bundleID()
      if not blocklist.isMusicApp(bid, config.musicApp.bundleID)
      and not blocklist.isBlocklisted(bid, config.blocklist)
      and not win:isMinimized() then
        toHide[bid] = app
      end
    end
  end

  local count = 0
  for _, app in pairs(toHide) do
    app:hide()
    count = count + 1
  end
  log.info("prepareWorkspace: hid apps", { count=count })
  return count
end

return M
```

### `boundary/window.lua`

Window polling, watcher, setFrame. `musicWindowOf`, `waitForWindow`, `launchAndResize` all
move here.

```lua
local log    = require("boundary.log")
local notify = require("boundary.notify")
local config = require("config")
local M = {}

--- Returns the first usable window for the music app.
function M.musicWindowOf(app)
  return app:mainWindow() or (app:allWindows() or {})[1]
end

--- Polls for the music app window, then focuses and resizes it.
function M.waitAndResize(app, targetFrame, remaining)
  local win = M.musicWindowOf(app)
  if win then
    log.info("window ready", { polls=(121-remaining) })
    win:focus()
    win:setFrame(targetFrame)
    notify.show("Music workspace ready")
  elseif remaining > 0 then
    hs.timer.doAfter(0.5, function() M.waitAndResize(app, targetFrame, remaining - 1) end)
  else
    log.warn("timed out waiting for window", { app=app:name() })
  end
end

--- Launches (or focuses) the music app and resizes its window to targetFrame.
function M.launchAndResize(targetFrame)
  local app = hs.application.get(config.musicApp.bundleID)
           or hs.application.find(config.musicApp.name)
  if app then
    local win = M.musicWindowOf(app)
    if win then
      win:focus()
      hs.timer.doAfter(0.3, function()
        win:setFrame(targetFrame)
        notify.show("Music workspace ready")
      end)
      return
    end
  end

  notify.show("Opening " .. config.musicApp.name .. "…")
  local _watcher
  _watcher = hs.application.watcher.new(function(_, event, launched)
    if launched:bundleID() ~= config.musicApp.bundleID then return end
    if event == hs.application.watcher.launched
    or event == hs.application.watcher.activated then
      _watcher:stop()
      M.waitAndResize(launched, targetFrame, 120)
    end
  end)
  _watcher:start()
  hs.application.launchOrFocusByBundleID(config.musicApp.bundleID)
end

return M
```

### `boundary/keyboard.lua`

The Save-As keystroke choreography from `autoSaveIfRunning`.

```lua
local M = {}

--- Sends the Ableton Save-As key sequence and types the given filename.
--- continuation() is called when the sequence is complete.
function M.saveAs(app, filename, continuation)
  app:activate()
  hs.timer.doAfter(0.4, function()
    hs.eventtap.keyStroke({"cmd","shift"}, "s")
    hs.timer.doAfter(0.6, function()
      hs.eventtap.keyStroke({"cmd"}, "a")
      hs.timer.doAfter(0.1, function()
        hs.eventtap.keyStrokes(filename)
        hs.timer.doAfter(0.1, function()
          hs.eventtap.keyStroke({}, "return")
          hs.timer.doAfter(1.2, continuation)
        end)
      end)
    end)
  end)
end

return M
```

### `boundary/notify.lua`

Thin wrapper around `hs.alert.show` so modules don't reference `hs.*` directly.

```lua
local M = {}

function M.show(msg)
  hs.alert.show(msg)
end

return M
```

### `boundary/clock.lua`

The only file allowed to read the wall clock. It keeps `core/` pure: `core/` receives
timestamps as plain strings, and this file is what produces them. Moving `os.date` here is
what lets the phase-6 glue stay effect-free.

```lua
local M = {}

--- Returns the current time as "YYYYMMDD_HHMMSS".
--- os.date can return a table for some format strings; this format always returns a
--- string, so the cast tells the language server the concrete type.
---@return string
function M.stamp()
  return os.date("%Y%m%d_%H%M%S") --[[@as string]]
end

return M
```

## The leak guard

After all boundary files are written, activate the `just leak-guard` recipe (already in the
`justfile` from phase 0). Run it manually to confirm it passes:

```bash
just leak-guard
```

It must exit zero. Any failure names the exact file and line that still calls an effectful
primitive outside `boundary/`.

## Done when

- Every boundary file above exists and is correct: `shell`, `applescript`, `screen`,
  `apps` (including `musicApp`), `window`, `keyboard`, `notify`, `clock`.
- `just leak-guard` exits zero. That means: no `hs.execute(`, `io.popen(`, or `os.execute(`
  outside `boundary/`; `core/` contains no `hs.*` and no wall-clock read; and the feature
  glue reaches no `hs.*` directly.
- Hammerspoon reloads cleanly: `hs -c 'hs.reload()'` and the menu bar icon is still present.
