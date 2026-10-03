-- Keeps the zpkt harness (lib/harness: browser -> Mac Claude Code jobs) running.
--
-- It runs under Hammerspoon rather than launchd because the code and the jobs
-- live in ~/Desktop, which macOS guards per app. Hammerspoon already has
-- Desktop and Accessibility access, and its children inherit both, so jobs can
-- read the repos and drive Live through System Events with no new grants.
local M = {}

local HOME = os.getenv("HOME")
local DIR = HOME .. "/Desktop/zpkt/lib/harness"
local LOG = HOME .. "/_agent_scratch/jobs/harness.log"
local UV = HOME .. "/.local/bin/uv"
local RESTART_S = 30

local task, timer

local function log(line)
  local f = io.open(LOG, "a")
  if f then f:write(os.date("%Y-%m-%d %H:%M:%S "), line, "\n"); f:close() end
end

local function start()
  hs.fs.mkdir(HOME .. "/_agent_scratch")
  hs.fs.mkdir(HOME .. "/_agent_scratch/jobs")
  local function out(_, stdout, stderr)
    if stdout and #stdout > 0 then log(stdout:gsub("\n$", "")) end
    if stderr and #stderr > 0 then log(stderr:gsub("\n$", "")) end
    return true
  end
  task = hs.task.new(UV, function(code)
    log("harness exited " .. tostring(code) .. "; restarting in " .. RESTART_S .. " s")
    task = nil
    timer = hs.timer.doAfter(RESTART_S, start)
  end, out, { "run", "--project", DIR, "harness", "serve" })
  task:setWorkingDirectory(HOME .. "/Desktop")
  local env = task:environment()
  env.PATH = HOME .. "/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  env.PYTHONUNBUFFERED = "1"
  task:setEnvironment(env)
  task:start()
  log("harness started")
end

function M.start()
  if task and task:isRunning() then return end
  start()
end

function M.stop()
  if timer then timer:stop(); timer = nil end
  if task then task:setCallback(nil); task:terminate(); task = nil end
end

return M
