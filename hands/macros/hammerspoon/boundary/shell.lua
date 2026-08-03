local log = require("boundary.log")
local M = {}

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
  local r = M.run(string.format("cp %q %q", src, dst))
  if not r.ok then
    return nil, "cp failed: " .. r.out
  end
  return true, nil
end

--- Opens a file with the given app bundle ID.
function M.openWithBundle(bundleID, path)
  local r = M.run(string.format("open -b %q %q", bundleID, path))
  if not r.ok then
    log.warn("shell.openWithBundle failed", { bundleID=bundleID, path=path, out=r.out })
  end
  return r.ok
end

return M
