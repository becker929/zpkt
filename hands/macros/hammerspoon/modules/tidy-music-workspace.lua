--[[
  tidy-music-workspace.lua

  Activates the Music Workspace: quits distracting apps, hides everything
  else, then launches and sizes the music app to fill the current screen.

  Architecture: pure core functions first, imperative shell below.
  Public API at the bottom.
]]

local config = require("config")
local log    = require("boundary.log")

local M = {}

-- ============================================================
-- Pure core
-- ============================================================

local function isMusicApp(bundleID)
  return bundleID == config.musicApp.bundleID
end

local function isBlocklisted(bundleID)
  for _, entry in ipairs(config.blocklist) do
    if entry.bundleID == bundleID then return true end
  end
  return false
end

-- mainWindow() returns nil for minimized or cross-Space windows; allWindows()[1] is reliable.
local function musicWindowOf(app)
  return app:mainWindow() or (app:allWindows() or {})[1]
end

-- Strips characters unsafe in a filename, collapses repeated underscores,
-- and trims leading/trailing underscores.
local function sanitizeFilePart(s)
  return s:gsub("[^%w%-]", "_"):gsub("_+", "_"):gsub("^_", ""):gsub("_$", "")
end

-- ============================================================
-- Imperative shell
-- ============================================================

-- Runs a checked-in AppleScript from ~/.hammerspoon/scripts/<name>.applescript.
-- Returns trimmed stdout on success (exit code 0), or nil if cancelled/errored.
local function runScript(name)
  local path = hs.configdir .. "/scripts/" .. name .. ".applescript"
  local out, status = hs.execute('osascript "' .. path .. '" 2>&1')
  if not status then
    log.warn("runScript: " .. name .. " failed", { out = tostring(out):gsub("%s+$", "") })
    return nil
  end
  return out:gsub("%s+$", "")
end

-- Returns the screen the mouse pointer is on, falling back to mainScreen.
local function screenUnderMouse()
  local pos = hs.mouse.absolutePosition()
  for _, screen in ipairs(hs.screen.allScreens()) do
    local f = screen:frame()
    if pos.x >= f.x and pos.x < f.x + f.w
   and pos.y >= f.y and pos.y < f.y + f.h then
      return screen
    end
  end
  return hs.screen.mainScreen()
end

-- Quits blocklisted apps, then hides all other visible apps instantly
-- (app:hide avoids the minimize genie animation).
-- Returns the number of apps hidden.
local function prepareWorkspace()
  for _, entry in ipairs(config.blocklist) do
    local app = hs.application.get(entry.bundleID)
             or hs.application.find(entry.name)
    if app then
      log.info("killing blocklisted app", { name = entry.name, bundleID = entry.bundleID })
      app:kill()
    end
  end

  local appsToHide = {}
  for _, win in ipairs(hs.window.allWindows()) do
    local app = win:application()
    if app then
      local bid = app:bundleID()
      if not isMusicApp(bid) and not isBlocklisted(bid) and not win:isMinimized() then
        appsToHide[bid] = app
      end
    end
  end

  local count = 0
  for _, app in pairs(appsToHide) do
    log.debug("hiding app", { bundleID = app:bundleID() or "unknown" })
    app:hide()
    count = count + 1
  end
  log.info("prepareWorkspace done", { hidCount = count })
  return count
end

-- Polls for the music app's window every 0.5 s, then focuses and resizes it.
-- Gives up after `remaining` attempts (~60 s at default 120).
local function waitForWindow(app, targetFrame, remaining)
  local win = musicWindowOf(app)
  if win then
    log.info("waitForWindow: window ready", { polls = 121 - remaining })
    win:focus()
    win:setFrame(targetFrame)
    hs.alert.show("Music workspace ready")
  elseif remaining > 0 then
    log.debug("waitForWindow: no window yet", { remaining = remaining })
    hs.timer.doAfter(0.5, function() waitForWindow(app, targetFrame, remaining - 1) end)
  else
    log.warn("waitForWindow: timed out", { app = app:name() or "unknown" })
  end
end

-- Launches (or focuses) the music app and resizes its window to targetFrame.
-- Uses an app watcher instead of busy-waiting, so the caller is not blocked.
local function launchAndResize(targetFrame)
  log.debug("launchAndResize: starting", { frame = tostring(targetFrame) })
  local app = hs.application.get(config.musicApp.bundleID)
           or hs.application.find(config.musicApp.name)

  if app then
    local win = musicWindowOf(app)
    if win then
      log.info("launchAndResize: app running with window, resizing directly")
      win:focus()
      hs.timer.doAfter(0.3, function()
        win:setFrame(targetFrame)
        hs.alert.show("Music workspace ready")
      end)
      return
    else
      log.info("launchAndResize: app running but no window yet, falling through to watcher")
    end
  else
    log.info("launchAndResize: app not running, launching via bundleID")
  end

  -- App is not running (or has no window yet) — launch and watch.
  hs.alert.show("Opening " .. config.musicApp.name .. "…")
  local _watcher
  _watcher = hs.application.watcher.new(function(_, event, launchedApp)
    if launchedApp:bundleID() ~= config.musicApp.bundleID then return end
    if event == hs.application.watcher.launched
    or event == hs.application.watcher.activated then
      log.info("launchAndResize: watcher event", { event = tostring(event), bundleID = launchedApp:bundleID() })
      _watcher:stop()
      waitForWindow(launchedApp, targetFrame, 120)
    end
  end)
  _watcher:start()
  hs.application.launchOrFocusByBundleID(config.musicApp.bundleID)
end

-- If the music app is running, prompts for a task name via AppleScript dialog,
-- then saves the current project as a new timestamped file via Cmd+Shift+S.
-- Calls continuation() when done (or immediately if app is absent or user skips).
local function autoSaveIfRunning(continuation)
  local app = hs.application.get(config.musicApp.bundleID)
           or hs.application.find(config.musicApp.name)
  if not app then
    log.debug("autoSaveIfRunning: music app not running, skipping save")
    continuation()
    return
  end
  log.debug("autoSaveIfRunning: music app is running")

  local out = runScript("task_name_prompt")
  log.debug("autoSaveIfRunning: script returned", { out = tostring(out) })
  if not out or out == "SKIP" then
    log.debug("autoSaveIfRunning: user skipped save")
    continuation()
    return
  end

  local taskName = out:match("^SAVE:(.*)")
  local part = sanitizeFilePart(taskName or "")
  local filename = os.date("%Y%m%d_%H%M%S") .. (part ~= "" and ("_" .. part) or "")
  log.info("autoSaveIfRunning: saving project", { filename = filename })

  app:activate()
  hs.timer.doAfter(0.4, function()
    hs.eventtap.keyStroke({"cmd", "shift"}, "s")        -- open Save As dialog
    hs.timer.doAfter(0.6, function()
      hs.eventtap.keyStroke({"cmd"}, "a")               -- select existing filename
      hs.timer.doAfter(0.1, function()
        hs.eventtap.keyStrokes(filename)                 -- type new filename
        hs.timer.doAfter(0.1, function()
          hs.eventtap.keyStroke({}, "return")            -- confirm
          hs.timer.doAfter(1.2, function()
            log.debug("autoSaveIfRunning: save sequence complete")
            continuation()
          end)
        end)
      end)
    end)
  end)
end

-- ============================================================
-- Public API
-- ============================================================

--[[
  M.activate()
  Enters music mode:
    1. If the music app is running, prompt to auto-save with a timestamp.
    2. Quit blocklisted apps.
    3. Hide all other visible apps instantly (no minimize animation).
    4. Launch or focus the music app; resize to fill the screen under the mouse.
]]
function M.activate()
  log.info("activate: starting")
  autoSaveIfRunning(function()
    local count = prepareWorkspace()
    if count > 0 then
      hs.alert.show("Hiding " .. count .. " apps…")
    end
    launchAndResize(screenUnderMouse():frame())
  end)
end

--[[
  M.openProjectCopy()
  Opens a file picker (AppleScript) to select an Ableton project (.als),
  copies it with a timestamp suffix, then activates the workspace and opens
  the copy. Triggered by Option+click on the menu bar icon.
]]
function M.openProjectCopy()
  log.info("openProjectCopy: starting")
  local src = runScript("choose_als_file")
  if not src then
    log.debug("openProjectCopy: no file selected")
    return
  end
  log.debug("openProjectCopy: src", { src = src })

  local dir  = src:match("^(.+)/[^/]+$") or "."
  local name = src:match("/([^/]+)%.als$") or "project"
  local dst  = dir .. "/" .. name .. "_copy_" .. os.date("%Y%m%d_%H%M%S") .. ".als"
  log.debug("openProjectCopy: dst", { dst = dst })

  local rc = os.execute(string.format("cp %q %q", src, dst))
  local cpOk = (rc == true) or (rc == 0)
  if not cpOk then
    log.warn("openProjectCopy: cp failed", { src = src })
    hs.alert.show("Music Workspace: could not copy project")
    return
  end

  local count = prepareWorkspace()
  if count > 0 then
    hs.alert.show("Hiding " .. count .. " apps…")
  end

  hs.alert.show("Opening copy…")
  local openOut, openOk = hs.execute(string.format("open -b %q %q", config.musicApp.bundleID, dst) .. " 2>&1")
  if not openOk then
    log.warn("openProjectCopy: open failed", { out = openOut })
  end
  launchAndResize(screenUnderMouse():frame())
end

return M
