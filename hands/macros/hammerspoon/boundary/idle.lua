local M = {}

--- Returns the number of seconds since the last user input (mouse or
--- keyboard), system-wide.
---@return number
function M.seconds()
  return hs.host.idleTime()
end

return M
