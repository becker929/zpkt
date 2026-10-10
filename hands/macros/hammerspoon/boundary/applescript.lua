local shell = require("boundary.shell")
local M = {}

--- Runs a checked-in AppleScript from ~/.hammerspoon/scripts/<name>.applescript.
--- Returns trimmed stdout on success, or nil if cancelled / errored.
function M.run(name)
  local path = hs.configdir .. "/scripts/" .. name .. ".applescript"
  local r = shell.run("osascript " .. shell.quote(path))
  if not r.ok then return nil end
  return r.out:gsub("%s+$", "")
end

return M
