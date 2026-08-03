local M = {}

--- Strips unsafe filename characters, collapses repeated underscores,
--- trims leading/trailing underscores.
---@param s string
---@return string
function M.sanitize(s)
  return (s:gsub("[^%w%-]", "_"):gsub("_+", "_"):gsub("^_", ""):gsub("_$", ""))
end

--- Builds a timestamped filename part: "20260802_143000" or "20260802_143000_task_name".
---@param stamp string  result of os.date("%Y%m%d_%H%M%S"), passed in by the caller
---@param part string   already-sanitized task name, or "" for no suffix
---@return string
function M.timestampedName(stamp, part)
  if part == "" then return stamp end
  return stamp .. "_" .. part
end

--- Derives the destination path for an .als copy.
---@param src string    "/path/to/project.als"
---@param stamp string  result of os.date("%Y%m%d_%H%M%S")
---@return string       "/path/to/project_copy_20260802_143000.als"
function M.copyPath(src, stamp)
  local dir  = src:match("^(.+)/[^/]+$") or "."
  local name = src:match("/([^/]+)%.als$") or "project"
  return dir .. "/" .. name .. "_copy_" .. stamp .. ".als"
end

--- Parses the AppleScript dialog result from task_name_prompt.applescript.
--- skipped is true if the user clicked Skip or the input is empty/nil.
--- taskName is "" when skipped.
---@param raw string|nil
---@return string   taskName
---@return boolean  skipped
function M.parseTaskPrompt(raw)
  if not raw or raw == "SKIP" then return "", true end
  local name = raw:match("^SAVE:(.*)")
  if not name then return "", true end
  return name, false
end

return M
