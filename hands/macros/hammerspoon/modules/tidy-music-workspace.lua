local filename    = require("core.filename")
local applescript = require("boundary.applescript")
local apps        = require("boundary.apps")
local window      = require("boundary.window")
local screen      = require("boundary.screen")
local keyboard    = require("boundary.keyboard")
local shell       = require("boundary.shell")
local notify      = require("boundary.notify")
local clock       = require("boundary.clock")
local log         = require("boundary.log")
local config      = require("config")

local M = {}

local function _prepareAndLaunch()
  local count = apps.prepareWorkspace()
  if count > 0 then notify.show("Hiding " .. count .. " apps…") end
  window.launchAndResize(screen.underMouse())
end

function M.activate()
  log.info("activate: starting")

  local app = apps.musicApp()
  if app then
    local raw = applescript.run("task_name_prompt")
    local taskName, skipped = filename.parseTaskPrompt(raw)
    if not skipped then
      local part  = filename.sanitize(taskName)
      local stamp = clock.stamp()
      local fname = filename.timestampedName(stamp, part)
      keyboard.saveAs(app, fname, function()
        log.info("activate: save complete, continuing")
        _prepareAndLaunch()
      end)
      return
    end
  end
  _prepareAndLaunch()
end

function M.openProjectCopy()
  log.info("openProjectCopy: starting")
  local src = applescript.run("choose_als_file")
  if not src then return end

  local dst = filename.copyPath(src, clock.stamp())

  local ok, err = shell.copyFile(src, dst)
  if not ok then
    log.warn("openProjectCopy: copy failed", { err=err })
    notify.show("Music Workspace: could not copy project")
    return
  end

  local count = apps.prepareWorkspace()
  if count > 0 then notify.show("Hiding " .. count .. " apps…") end
  notify.show("Opening copy…")
  shell.openWithBundle(config.musicApp.bundleID, dst)
  window.launchAndResize(screen.underMouse())
end

return M
