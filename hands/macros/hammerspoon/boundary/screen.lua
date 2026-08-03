local geometry = require("core.geometry")
local M = {}

--- Returns the frame of the screen the mouse pointer is on.
--- Falls back to mainScreen. Uses core.geometry.pointInRect for the pure test.
function M.underMouse()
  local pos = hs.mouse.absolutePosition()
  for _, screen in ipairs(hs.screen.allScreens()) do
    local f = screen:frame()
    if geometry.pointInRect(pos.x, pos.y, f) then
      return f
    end
  end
  return hs.screen.mainScreen():frame()
end

return M
