local M = {}

--- Returns the current time as "YYYYMMDD_HHMMSS".
--- os.date can return a table for some format strings; this format always returns a
--- string, so the cast tells the language server the concrete type.
---@return string
function M.stamp()
  return os.date("%Y%m%d_%H%M%S") --[[@as string]]
end

return M
