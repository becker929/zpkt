local applescript = require("boundary.applescript")
local apps        = require("boundary.apps")
local autosave    = require("boundary.autosave")
local keyboard    = require("boundary.keyboard")
local shell       = require("boundary.shell")
local notify      = require("boundary.notify")
local clock       = require("boundary.clock")
local log         = require("boundary.log")
local backup      = require("core.backup")
local config      = require("config")

local M = {}

local _doExport

function M.export()
  local app = apps.musicApp()
  if app then
    autosave.touchRef()
    keyboard.save(app, function()
      local projectPath = autosave.findSaved(config.autoBackup.projectsDir)
      _doExport(projectPath)
    end)
  else
    _doExport(nil)
  end
end

_doExport = function(projectPath)
  log.info("auto-export: starting")
  local stamp      = clock.stamp()
  local outputPath = config.rendersDir .. "/" .. stamp .. ".wav"
  notify.show("Exporting…")
  local result = applescript.runWithArgs("export", { outputPath, "WAV", "24", "44100" })
  if not result then
    log.warn("auto-export: export script returned nil")
    notify.show("Export failed — check Ableton and try again")
    return
  end
  log.info("auto-export: complete", { path = result })
  shell.openInFinder(config.rendersDir)

  notify.show("Uploading…")
  local scriptPath = shell.configDir() .. "/scripts/upload-audio.sh"
  local r = shell.run("bash -l " .. string.format("%q", scriptPath) .. " " .. string.format("%q", result))
  if r.ok then
    log.info("auto-export: uploaded", { url = r.out:gsub("%s+$", "") })
    notify.show("Live: anthonybecker.me/audio")
  else
    log.warn("auto-export: upload failed", { out = r.out })
    notify.show("Upload failed — check logs")
  end

  if projectPath then
    local projectName = backup.projectNameFromPath(projectPath)
    autosave.cloneProjects(config.autoBackup.projectsDir, config.autoBackup.cloneDir, function()
      autosave.cleanupProjectBackups(config.autoBackup.backupsDir, projectName)
    end)
  end
end

return M
