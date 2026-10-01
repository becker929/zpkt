local shell  = require("boundary.shell")
local log    = require("boundary.log")
local backup = require("core.backup")

local M = {}

local REF_FILE = "/tmp/hs_bk_ref"

--- Stamps the reference file. Must be called before findSaved().
function M.touchRef()
  shell.run("touch " .. shell.quote(REF_FILE))
end

--- Returns the path of the .als file saved since touchRef(), or nil.
---@param projectsDir string
---@return string|nil
function M.findSaved(projectsDir)
  local r = shell.run(
    "find " .. shell.quote(projectsDir) ..
    " -name '*.als' -newer " .. shell.quote(REF_FILE) ..
    " 2>/dev/null"
  )
  if not r.ok or r.out == "" then return nil end
  return r.out:match("^([^\n]+)")
end

--- Creates a directory and all parents.
---@param dir string
---@return boolean
function M.ensureDir(dir)
  local r = shell.run("mkdir -p " .. shell.quote(dir))
  if not r.ok then
    log.warn("autosave.ensureDir: failed", { dir = dir, out = r.out })
  end
  return r.ok
end

--- Deletes the oldest backups so that at most maxVersions remain.
---@param backupsDir  string
---@param projectName string
---@param maxVersions number
function M.pruneBackups(backupsDir, projectName, maxVersions)
  local dir = backup.projectBackupDir(backupsDir, projectName)
  local r   = shell.run("ls -1 " .. shell.quote(dir) .. " 2>/dev/null")
  if r.out == "" then return end
  local files = {}
  for name in r.out:gmatch("[^\n]+") do
    if name:match("%.als$") then files[#files + 1] = name end
  end
  table.sort(files)
  for _, name in ipairs(backup.filesToDelete(files, maxVersions)) do
    local path = dir .. name
    shell.run("rm -f " .. shell.quote(path))
    log.info("autosave.pruneBackups: deleted", { path = path })
  end
end

--- Rsyncs the entire projects directory into iCloud in the background.
--- onDone(ok) is optional.
---@param projectsDir string
---@param cloneDir    string
---@param onDone      function|nil
function M.cloneProjects(projectsDir, cloneDir, onDone)
  local cmd = "rsync -a --delete " ..
    shell.quote(projectsDir .. "/") .. " " ..
    shell.quote(cloneDir)
  shell.runBackground(cmd, function(ok)
    if ok then
      log.info("autosave.cloneProjects: done", { dst = cloneDir })
    else
      log.warn("autosave.cloneProjects: failed", { dst = cloneDir })
    end
    if onDone then onDone(ok) end
  end)
end

--- Removes the per-project backup folder entirely (called after export).
---@param backupsDir  string
---@param projectName string
function M.cleanupProjectBackups(backupsDir, projectName)
  local dir = backup.projectBackupDir(backupsDir, projectName)
  local r   = shell.run("rm -rf " .. shell.quote(dir))
  if not r.ok then
    log.warn("autosave.cleanupProjectBackups: failed", { dir = dir, out = r.out })
  end
end

return M
