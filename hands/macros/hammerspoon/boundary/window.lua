local log    = require("boundary.log")
local notify = require("boundary.notify")
local config = require("config")
local M = {}

-- Time to let macOS register a focus change as "frontmost" before acting on
-- it (e.g. hiding other apps). win:focus() returns before the OS has fully
-- applied the activation, so calling onFocused synchronously races it.
local FOCUS_SETTLE_SECONDS = 0.15

local function _notifyFocused(onFocused)
  if not onFocused then return end
  hs.timer.doAfter(FOCUS_SETTLE_SECONDS, onFocused)
end

--- Returns the first usable window for the music app.
function M.musicWindowOf(app)
  return app:mainWindow() or (app:allWindows() or {})[1]
end

--- Returns whether the app's window has unsaved changes, via the
--- accessibility API's "AXModified" attribute (the same signal macOS uses
--- to show the dot in a window's close button). This does not require the
--- app to be focused.
--- Returns nil (unknown) if the app has no window yet, or doesn't expose
--- this attribute — callers should treat nil the same as "assume dirty".
---@param app hs.application
---@return boolean|nil
function M.isModified(app)
  local win = M.musicWindowOf(app)
  if not win then return nil end
  local ok, axWin = pcall(hs.axuielement.windowElement, win)
  if not ok or not axWin then return nil end
  local ok2, modified = pcall(function() return axWin:attributeValue("AXModified") end)
  if not (ok2 and type(modified) == "boolean") then return nil end
  return modified
end

--- Returns the currently focused window (of any app), or nil.
function M.focused()
  return hs.window.focusedWindow()
end

--- Best-effort refocus of a previously-focused window, e.g. to restore
--- whatever the user was looking at before we stole focus.
function M.refocus(win)
  if not win then return end
  local ok = pcall(function() win:focus() end)
  if not ok then
    log.warn("window.refocus: failed")
  end
end

--- Polls for the music app window, then focuses and resizes it.
--- onFocused (optional) is invoked once macOS has registered the focus
--- change — e.g. to hide other apps once this one holds focus.
function M.waitAndResize(app, targetFrame, remaining, onFocused)
  local win = M.musicWindowOf(app)
  if win then
    log.info("window ready", { polls=(121-remaining) })
    win:focus()
    _notifyFocused(onFocused)
    win:setFrame(targetFrame)
    notify.show("Music workspace ready")
  elseif remaining > 0 then
    hs.timer.doAfter(0.5, function() M.waitAndResize(app, targetFrame, remaining - 1, onFocused) end)
  else
    log.warn("timed out waiting for window", { app=app:name() })
  end
end

--- Launches (or focuses) the music app and resizes its window to targetFrame.
--- onFocused (optional) is invoked once macOS has registered the focus
--- change — e.g. to hide other apps once this one holds focus.
function M.launchAndResize(targetFrame, onFocused)
  local app = hs.application.get(config.musicApp.bundleID)
           or hs.application.find(config.musicApp.name)
  if app then
    local win = M.musicWindowOf(app)
    if win then
      win:focus()
      _notifyFocused(onFocused)
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
      M.waitAndResize(launched, targetFrame, 120, onFocused)
    end
  end)
  _watcher:start()
  hs.application.launchOrFocusByBundleID(config.musicApp.bundleID)
end

return M
