require("hs.ipc")
local config    = require("config")
local workspace = require("modules.tidy-music-workspace")
local menubar   = require("modules.menubar")

menubar.init(function() workspace.activate() end)

local hk = config.hotkeys
if hk.activate then
  hs.hotkey.bind(hk.activate.mods, hk.activate.key, function() workspace.activate() end)
end
