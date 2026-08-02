-- Defensive pcall wrappers around hs.spaces (undocumented private API).
-- All functions return (result, errMsg). Callers check: if not result then ...

local M = {}

-- Returns a set {spaceID -> true} for all known Spaces, or (nil, errMsg).
function M.allSpaces()
  local ok, result = pcall(hs.spaces.allSpaces)
  if not ok or type(result) ~= "table" then
    return nil, "hs.spaces.allSpaces failed: " .. tostring(result)
  end
  -- hs.spaces.allSpaces() returns { screenUUID -> {spaceID, ...} }
  -- Flatten to a set for easy membership checks.
  local set = {}
  for _, spaceList in pairs(result) do
    if type(spaceList) == "table" then
      for _, spaceID in ipairs(spaceList) do
        set[spaceID] = true
      end
    end
  end
  return set, nil
end

-- Returns a list of Space IDs the given window belongs to, or (nil, errMsg).
function M.windowSpaces(windowID)
  local ok, result = pcall(hs.spaces.windowSpaces, windowID)
  if not ok then
    return nil, "hs.spaces.windowSpaces failed: " .. tostring(result)
  end
  if type(result) ~= "table" then
    return nil, "hs.spaces.windowSpaces returned unexpected type: " .. type(result)
  end
  return result, nil
end

-- Moves a window to the given Space. Returns (true, nil) or (nil, errMsg).
function M.moveWindowToSpace(window, spaceID)
  local ok, err = pcall(hs.spaces.moveWindowToSpace, window, spaceID)
  if not ok then
    return nil, "hs.spaces.moveWindowToSpace failed: " .. tostring(err)
  end
  return true, nil
end

return M
