-- Capture and persist full cross-Space window state to disk.

local spacesUtil = require("modules.spaces_util")
local config     = require("config")

local M = {}

-- Builds the snapshot table. Returns (table, nil) or (nil, errMsg).
-- spacesFailedFallback: if true, skip Space-ID lookup and use 0 as placeholder.
local function buildSnapshot(spacesFailedFallback)
  local snapshot = {
    version      = 1,
    capturedAt   = os.date("!%Y-%m-%dT%H:%M:%S"),
    quitApps     = {},
    windows      = {},
  }

  -- Record which blocklisted apps are currently running.
  for _, entry in ipairs(config.blocklist) do
    local app = hs.application.get(entry.bundleID)
              or hs.application.find(entry.name)
    if app then
      table.insert(snapshot.quitApps, {
        name     = entry.name,
        bundleID = entry.bundleID,
      })
    end
  end

  -- Enumerate all windows.
  for _, win in ipairs(hs.window.allWindows()) do
    local app = win:application()
    if not app then goto continue end

    local bundleID = app:bundleID() or ""
    local frame    = win:frame()

    -- Determine which Space this window is on.
    local spaceID = 0
    if not spacesFailedFallback then
      local spaces, _ = spacesUtil.windowSpaces(win:id())
      if spaces and spaces[1] then
        spaceID = spaces[1]
      end
    end

    table.insert(snapshot.windows, {
      windowID  = win:id(),
      appName   = app:name() or "",
      bundleID  = bundleID,
      title     = win:title() or "",
      frame     = { x = frame.x, y = frame.y, w = frame.w, h = frame.h },
      spaceID   = spaceID,
      minimized = win:isMinimized(),
    })

    ::continue::
  end

  return snapshot, nil
end

-- Captures full state. Returns (table, nil) or (nil, errMsg).
-- On hs.spaces failure, calls continueOrAbortFn(msg) and either falls back or returns nil.
function M.capture(continueOrAbortFn)
  -- Check spaces API is reachable before committing to a full capture.
  local spaces, err = spacesUtil.allSpaces()
  local fallback = false

  if not spaces then
    local choice = continueOrAbortFn("hs.spaces enumeration failed: " .. (err or "unknown"))
    if choice == "abort" then
      return nil, "aborted by user after spaces failure"
    end
    fallback = true
  end

  return buildSnapshot(fallback)
end

-- Atomically writes snapshot to disk. Returns (true, nil) or (nil, errMsg).
function M.save(snapshot)
  local ok, encoded = pcall(hs.json.encode, snapshot, true)
  if not ok or not encoded then
    return nil, "json encode failed: " .. tostring(encoded)
  end

  local tmpPath = config.snapshotPath .. ".tmp"

  local f, ferr = io.open(tmpPath, "w")
  if not f then
    return nil, "could not write snapshot: " .. tostring(ferr)
  end
  f:write(encoded)
  f:close()

  local renameOk, renameErr = os.rename(tmpPath, config.snapshotPath)
  if not renameOk then
    return nil, "could not rename snapshot: " .. tostring(renameErr)
  end

  return true, nil
end

-- Reads and decodes snapshot from disk. Returns (table, nil) or (nil, errMsg).
function M.load()
  local f = io.open(config.snapshotPath, "r")
  if not f then
    return nil, "no snapshot file"
  end
  local raw = f:read("*a")
  f:close()

  if not raw or raw == "" then
    return nil, "snapshot file is empty"
  end

  local ok, decoded = pcall(hs.json.decode, raw)
  if not ok or type(decoded) ~= "table" then
    return nil, "json decode failed: " .. tostring(decoded)
  end

  return decoded, nil
end

-- Deletes the snapshot file.
function M.clear()
  os.remove(config.snapshotPath)
end

return M
