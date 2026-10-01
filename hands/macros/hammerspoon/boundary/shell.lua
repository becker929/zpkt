local log = require("boundary.log")
local M = {}

--- POSIX-quote one shell word. Use for every interpolated value.
M.quote = require("core.shellquote").quote

--- Runs a shell command. Always captures stderr.
--- Returns ShResult: { ok, out, rawCode }
--- NEVER read rawCode to decide success — always use ok.
--- rawCode is the 3rd return of hs.execute: the string "exit" or "signal", NOT a number.
function M.run(cmd)
  local out, ok, rawCode = hs.execute(cmd .. " 2>&1")
  local result = { ok = (ok == true), out = out or "", rawCode = rawCode }
  log.debug("shell.run", { cmd=cmd, ok=result.ok, rawCode=rawCode })
  return result
end

--- Copies src to dst. Returns (true, nil) or (nil, errMsg).
function M.copyFile(src, dst)
  local r = M.run("cp " .. M.quote(src) .. " " .. M.quote(dst))
  if not r.ok then
    return nil, "cp failed: " .. r.out
  end
  return true, nil
end

--- Opens a file with the given app bundle ID.
function M.openWithBundle(bundleID, path)
  local r = M.run("open -b " .. M.quote(bundleID) .. " " .. M.quote(path))
  if not r.ok then
    log.warn("shell.openWithBundle failed", { bundleID=bundleID, path=path, out=r.out })
  end
  return r.ok
end

--- Runs a shell command in the background via hs.task.
--- onDone(ok) is called when the process exits; pass nil to fire-and-forget.
function M.runBackground(cmd, onDone)
  local t = hs.task.new("/bin/bash", function(code, out, err)
    local ok = (code == 0)
    log.debug("shell.runBackground", { cmd = cmd, ok = ok })
    if onDone then onDone(ok) end
  end, { "-c", cmd })
  t:start()
  return t
end

--- Returns the Hammerspoon config directory.
function M.configDir()
  return hs.configdir
end

--- Opens path in Finder.
function M.openInFinder(path)
  local r = M.run("open " .. M.quote(path))
  if not r.ok then log.warn("shell.openInFinder failed", { path=path, out=r.out }) end
  return r.ok
end

return M
