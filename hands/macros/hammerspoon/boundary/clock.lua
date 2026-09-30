local M = {}

--- Returns the current time as "YYYYMMDD_HHMMSS".
--- os.date can return a table for some format strings; this format always returns a
--- string, so the cast tells the language server the concrete type.
---@return string
function M.stamp()
  return os.date("%Y%m%d_%H%M%S") --[[@as string]]
end

--- Returns the current wall-clock time in seconds since the epoch.
--- Used for measuring elapsed time between events (e.g. backup intervals).
---@return number
function M.now()
  return os.time()
end

return M
