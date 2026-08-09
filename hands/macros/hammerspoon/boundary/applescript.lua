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

--- Runs a checked-in AppleScript with positional CLI arguments.
--- args is an ordered list of strings; each is shell-quoted.
--- Returns trimmed stdout on success, or nil if cancelled / errored.
function M.runWithArgs(name, args)
  local path = hs.configdir .. "/scripts/" .. name .. ".applescript"
  local quoted = {}
  for _, a in ipairs(args) do table.insert(quoted, string.format("%q", a)) end
  local cmd = 'osascript "' .. path .. '" ' .. table.concat(quoted, " ")
  local r = shell.run(cmd)
  if not r.ok then return nil end
  return r.out:gsub("%s+$", "")
end

return M
