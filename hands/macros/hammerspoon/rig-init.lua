-- Entry point for the headless Live rig (the Mac mini). It loads only the
-- A/B hotkeys: init.lua also starts auto-backup and quits chat apps, which
-- belong to a desk machine. Install with:
--   echo 'dofile(os.getenv("HOME") .. "/Desktop/zpkt/hands/macros/hammerspoon/rig-init.lua")' > ~/.hammerspoon/init.lua
require("hs.ipc")
local dir = os.getenv("HOME") .. "/Desktop/zpkt/hands/macros/hammerspoon/"
package.path = dir .. "?.lua;" .. package.path

local config = require("config")
require("modules.ab-hotkeys").bind(config.ab)
HARNESS = require("modules.harness")  -- global: hs.task is collected if nothing holds it
HARNESS.start()
hs.autoLaunch(true)
hs.alert.show("zpkt hotkeys ready", 1)
