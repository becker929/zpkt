--- POSIX shell quoting.
---
--- string.format("%q") produces a Lua string literal, not a shell word: inside
--- its double quotes the shell still expands $(...) and backticks, so a project
--- path containing them would execute. Single quotes stop all expansion; an
--- embedded single quote is closed, escaped, and reopened.
local M = {}

---@param s string
---@return string
function M.quote(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

return M
