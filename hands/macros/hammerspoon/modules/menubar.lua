-- Menu bar icon. Clicking it calls activateFn directly.
-- The menubar object is stored at module scope — GC would silently remove it otherwise.

local M = {}

local _menubar = nil

-- Creates the menu bar item and wires the click callback.
function M.init(activateFn)
  _menubar = hs.menubar.new()
  if _menubar then
    _menubar:setTitle("♪")
    _menubar:setClickCallback(activateFn)
  end
end

return M
