---@class Entry
---@field name string
---@field bundleID string

local M = {}

--- Returns true if bundleID matches the music app's bundle ID.
---@param bundleID string
---@param musicBundleID string
---@return boolean
function M.isMusicApp(bundleID, musicBundleID)
  return bundleID == musicBundleID
end

--- Returns true if bundleID is in the blocklist.
---@param bundleID string
---@param blocklist Entry[]
---@return boolean
function M.isBlocklisted(bundleID, blocklist)
  for _, entry in ipairs(blocklist) do
    if entry.bundleID == bundleID then return true end
  end
  return false
end

return M
