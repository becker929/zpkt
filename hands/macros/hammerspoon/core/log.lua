local M = {}

--- Builds a structured log record as a plain table.
--- The caller (boundary) encodes to JSON and writes to disk.
---@param level string  "debug" | "info" | "warn" | "error"
---@param msg string    human-readable description
---@param fields table<string, any>|nil  extra context (may be nil)
---@param ts integer    os.time() passed in by the caller (keeps this pure)
---@return table<string, any>
function M.record(level, msg, fields, ts)
  return {
    ts     = ts,
    level  = level,
    module = fields and fields.module or nil,
    msg    = msg,
    fields = fields,
  }
end

return M
