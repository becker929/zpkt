local apps     = require("boundary.apps")
local autosave = require("boundary.autosave")
local keyboard = require("boundary.keyboard")
local shell    = require("boundary.shell")
local clock    = require("boundary.clock")
local log      = require("boundary.log")
local backup   = require("core.backup")

local M = {}

local _timer = nil
local _cfg   = nil

function M.runOnce()
  if not _cfg then return end
  local app = apps.musicApp()
  if not app then return end

  autosave.touchRef()
  keyboard.save(app, function()
    local projectPath = autosave.findSaved(_cfg.projectsDir)
    if not projectPath then
      log.info("auto-backup: no saved .als found, skipping")
      return
    end
    local projectName = backup.projectNameFromPath(projectPath)
    autosave.ensureDir(backup.projectBackupDir(_cfg.backupsDir, projectName))
    local dst = backup.backupPath(_cfg.backupsDir, projectName, clock.stamp())
    local ok, err = shell.copyFile(projectPath, dst)
    if not ok then
      log.warn("auto-backup: copy failed", { err = err })
      return
    end
    autosave.pruneBackups(_cfg.backupsDir, projectName, _cfg.maxVersions)
    log.info("auto-backup: backed up", { path = dst })
    if _cfg.cloneDir then
      autosave.cloneProjects(_cfg.projectsDir, _cfg.cloneDir, nil)
    end
  end)
end

function M.start(cfg)
  _cfg = cfg
  local interval = (cfg.intervalMinutes or 5) * 60
  _timer = hs.timer.doEvery(interval, M.runOnce)
  log.info("auto-backup: started", { intervalMinutes = cfg.intervalMinutes or 5 })
end

function M.stop()
  if _timer then
    _timer:stop()
    _timer = nil
  end
end

return M
