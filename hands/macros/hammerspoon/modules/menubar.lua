-- Menu bar icon. Left-click calls activateFn; Option+click calls openCopyFn;
-- Ctrl+click opens a dropdown with all three actions.
-- The menubar object is stored at module scope — GC would silently remove it otherwise.

local M = {}

local _menubar = nil

-- Creates the menu bar item and wires the click callback.
-- activateFn: called on plain click
-- openCopyFn: called on Option+click
-- exportFn:   accessible via Ctrl+click dropdown
function M.init(activateFn, openCopyFn, exportFn)
  _menubar = hs.menubar.new()
  if _menubar then
    _menubar:setTitle("♪")
    _menubar:setMenu(function()
      local mods = hs.eventtap.checkKeyboardModifiers()
      if mods.ctrl then
        return {
          { title = "Activate Workspace", fn = activateFn },
          { title = "Open Project Copy",  fn = openCopyFn },
          { title = "Export",             fn = exportFn   },
        }
      elseif mods.alt then
        openCopyFn()
        return nil
      else
        activateFn()
        return nil
      end
    end)
  end
end

return M
