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
