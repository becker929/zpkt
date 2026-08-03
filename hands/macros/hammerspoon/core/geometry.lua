---@class Rect
---@field x number
---@field y number
---@field w number
---@field h number

local M = {}

--- Returns true if the point (x, y) lies inside the rectangle
--- (inclusive of the top-left edge, exclusive of the bottom-right edge).
---@param x number
---@param y number
---@param r Rect
---@return boolean
function M.pointInRect(x, y, r)
  return x >= r.x and x < r.x + r.w and y >= r.y and y < r.y + r.h
end

return M
