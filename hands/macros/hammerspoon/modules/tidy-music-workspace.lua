--[[
  tidy-music-workspace.lua

  Activates the Music Workspace: quits distracting apps, hides everything
  else, then launches and sizes the music app to fill the current screen.

  Architecture: functions that only transform data are in the Pure Core
  section. Functions that touch the OS are in the Imperative Shell section.
  The public API is at the bottom.
]]

local config = require("config")

local M = {}

-- ============================================================
-- Pure core
-- ============================================================

-- True if bundleID matches the configured music application.
local function isMusicApp(bundleID)
  return bundleID == config.musicApp.bundleID
end

-- True if bundleID appears in config.blocklist.
local function isBlocklisted(bundleID)
  for _, entry in ipairs(config.blocklist) do
    if entry.bundleID == bundleID then return true end
  end
  return false
end

-- ============================================================
-- Imperative shell
-- ============================================================

-- Busy-waits for the music app process up to timeout seconds.
-- Returns the hs.application object or nil.
local function pollForMusicApp(timeout)
  local deadline = os.time() + timeout
  local app
  repeat
    app = hs.application.get(config.musicApp.bundleID)
       or hs.application.find(config.musicApp.name)
    if not app then hs.timer.usleep(200000) end  -- 0.2 s
  until app or os.time() >= deadline
  return app
end

-- Busy-waits for app's main window up to timeout seconds.
-- Returns the hs.window object or nil.
local function pollForMainWindow(app, timeout)
  local deadline = os.time() + timeout
  local win
  repeat
    win = app:mainWindow()
    if not win then hs.timer.usleep(200000) end  -- 0.2 s
  until win or os.time() >= deadline
  return win
end

-- Returns the screen the mouse pointer is on. Falls back to mainScreen.
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

-- ============================================================
-- Public API
-- ============================================================

--[[
  M.activate()
  Enters music mode:
    1. Quit blocklisted apps.
    2. Minimize all other visible windows.
    3. Launch or focus the music app; wait up to 10 s.
    4. Resize the music app to fill the screen under the mouse.
]]
function M.activate()
  for _, entry in ipairs(config.blocklist) do
    local app = hs.application.get(entry.bundleID)
             or hs.application.find(entry.name)
    if app then app:kill() end
  end

  for _, win in ipairs(hs.window.allWindows()) do
    local app = win:application()
    if app then
      local bid = app:bundleID()
      if not isMusicApp(bid) and not isBlocklisted(bid) and not win:isMinimized() then
        win:minimize()
      end
    end
  end

  hs.application.launchOrFocusByBundleID(config.musicApp.bundleID)
  local musicApp = pollForMusicApp(10)
  if not musicApp then
    hs.alert.show("Music Workspace: music app did not launch within 10s")
    return
  end

  local musicWin = pollForMainWindow(musicApp, 5)
  if not musicWin then
    hs.alert.show("Music Workspace: music app window did not appear within 5s")
    return
  end

  local targetFrame = screenUnderMouse():frame()
  musicWin:focus()
  hs.timer.doAfter(0.5, function() musicWin:setFrame(targetFrame) end)
end

return M
