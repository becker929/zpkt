local blocklist = require("core.blocklist")
local log       = require("boundary.log")
local config    = require("config")
local M = {}

--- Returns the running music app handle, or nil if it is not running.
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
