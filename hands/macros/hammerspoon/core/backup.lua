local M = {}

--- Extracts the project name from an .als path.
---@param projectPath string  "/path/to/MyTrack.als"
---@return string             "MyTrack"
function M.projectNameFromPath(projectPath)
  return projectPath:match("/([^/]+)%.als$") or "project"
end

--- Returns the per-project backup directory.
---@param backupsDir  string  root iCloud backups dir
---@param projectName string
---@return string             "<backupsDir>/<projectName>/"
function M.projectBackupDir(backupsDir, projectName)
  return backupsDir .. "/" .. projectName .. "/"
end

--- Returns the full path for one backup file.
---@param backupsDir  string
---@param projectName string
---@param stamp       string  os.date result e.g. "20260804_090000"
---@return string
function M.backupPath(backupsDir, projectName, stamp)
  return backupsDir .. "/" .. projectName .. "/" .. projectName .. "_" .. stamp .. ".als"
end

--- Given a sorted-ascending list of backup filenames, returns the ones
--- to delete so that only maxKeep remain.
---@param filenames table   sorted ascending (oldest first)
---@param maxKeep   number
---@return table
function M.filesToDelete(filenames, maxKeep)
  if #filenames <= maxKeep then return {} end
  local result = {}
  for i = 1, #filenames - maxKeep do
    result[#result + 1] = filenames[i]
  end
  return result
end

return M
