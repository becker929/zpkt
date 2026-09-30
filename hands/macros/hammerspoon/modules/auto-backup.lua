local apps     = require("boundary.apps")
local autosave = require("boundary.autosave")
local keyboard = require("boundary.keyboard")
local shell    = require("boundary.shell")
local clock    = require("boundary.clock")
local window   = require("boundary.window")
local idle     = require("boundary.idle")
local log      = require("boundary.log")
local backup   = require("core.backup")

local M = {}

-- How often we check whether it's time to try a backup. Small compared to
-- the backup interval / idle threshold so we notice promptly once the user
-- goes idle, without polling so tightly it's wasteful.
local POLL_SECONDS = 15

local _timer        = nil
local _cfg          = nil
local _lastBackupAt = 0

--- Saves + backs up the current project. Assumes the caller has already
--- decided this is a good time to steal focus (idle user, dirty project).
function M.runOnce()
  if not _cfg then return end
  local app = apps.musicApp()
  if not app then return end

  local previouslyFocused = window.focused()

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
  end, function()
    -- Fired right after the save keystroke, well before the continuation
    -- above finishes copying files -- restoring focus doesn't need to wait
    -- on any of that.
    window.refocus(previouslyFocused)
  end)
end

--- Checks whether a backup is due (enough time elapsed) and safe (the user
--- has been idle long enough, and the project actually has unsaved
--- changes), and runs one if so.
local function _tick()
  if not _cfg then return end

  local intervalSeconds = (_cfg.intervalMinutes or 5) * 60
  if clock.now() - _lastBackupAt < intervalSeconds then return end

  local idleSeconds = _cfg.idleSeconds or 120
  if idle.seconds() < idleSeconds then
    log.debug("auto-backup: user active, waiting")
    return
  end

  local app = apps.musicApp()
  if not app then return end

  -- Best-effort dirty check without focusing the app. If we can't tell
  -- (nil), fall back to saving anyway -- same as the old unconditional
  -- behavior.
  if window.isModified(app) == false then
    log.debug("auto-backup: no unsaved changes, skipping")
    _lastBackupAt = clock.now()
    return
  end

  _lastBackupAt = clock.now()
  M.runOnce()
end

function M.start(cfg)
  _cfg          = cfg
  _lastBackupAt = clock.now()
  _timer = hs.timer.doEvery(POLL_SECONDS, _tick)
  log.info("auto-backup: started", {
    intervalMinutes = cfg.intervalMinutes or 5,
    idleSeconds      = cfg.idleSeconds or 120,
  })
end

function M.stop()
  if _timer then
    _timer:stop()
    _timer = nil
  end
end

return M
