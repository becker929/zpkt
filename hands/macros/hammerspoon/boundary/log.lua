local logCore = require("core.log")

local M = {}
local PATH = hs.configdir .. "/.logs/hs.jsonl"

function M.write(level, msg, fields)
  local rec = logCore.record(level, msg, fields, os.time())
  local ok, encoded = pcall(hs.json.encode, rec)
  if not ok then return end
  local f = io.open(PATH, "a")
  if not f then return end
  f:write(encoded .. "\n")
  f:close()
end

function M.debug(msg, fields) M.write("debug", msg, fields) end
function M.info(msg, fields)  M.write("info",  msg, fields) end
function M.warn(msg, fields)  M.write("warn",  msg, fields) end
function M.error(msg, fields) M.write("error", msg, fields) end

return M
