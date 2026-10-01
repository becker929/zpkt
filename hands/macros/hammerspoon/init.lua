require("hs.ipc")
local config      = require("config")
local workspace   = require("modules.tidy-music-workspace")
local autoExport  = require("modules.auto-export")
local autoBackup  = require("modules.auto-backup")
local menubar     = require("modules.menubar")
local abHotkeys   = require("modules.ab-hotkeys")

abHotkeys.bind(config.ab)

autoBackup.start(config.autoBackup)

menubar.init(
  function() workspace.activate() end,
  function() workspace.openProjectCopy() end,
  function() autoExport.export() end
)

local hk = config.hotkeys
if hk.activate then
  hs.hotkey.bind(hk.activate.mods, hk.activate.key, function() workspace.activate() end)
end
