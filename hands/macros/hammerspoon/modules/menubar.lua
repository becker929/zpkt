-- Menu bar icon. Left-click calls activateFn; Option+click calls openCopyFn.
-- The menubar object is stored at module scope — GC would silently remove it otherwise.

local M = {}

local _menubar = nil

-- Creates the menu bar item and wires the click callback.
-- activateFn: called on plain click
-- openCopyFn: called on Option+click
function M.init(activateFn, openCopyFn)
  _menubar = hs.menubar.new()
  if _menubar then
    _menubar:setTitle("♪")
    _menubar:setClickCallback(function()
      local mods = hs.eventtap.checkKeyboardModifiers()
      if mods.alt and openCopyFn then
        openCopyFn()
      else
        activateFn()
      end
    end)
  end
end

return M
