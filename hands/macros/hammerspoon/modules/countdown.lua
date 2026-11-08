-- Cancellable countdown before an agent does something disruptive (reload Live, change the audio
-- device, quit an app). Shows "<what> in 10... 9..." with a Cancel button; Esc also cancels.
-- The result is written to a file so a shell can wait on it without blocking Hammerspoon:
--   "go" when the countdown ran out, "cancel" when the user cancelled.
-- Started by hands/macros/hammerspoon/scripts/rig-confirm.sh (which loads this module on demand,
-- so no Hammerspoon reload is needed).
local M = {}
local active = nil

local function finish(state, result)
  if state.done then return end
  state.done = true
  if state.timer then state.timer:stop() end
  if state.esc then state.esc:delete() end
  if state.canvas then state.canvas:delete() end
  local f = io.open(state.path, "w")
  if f then f:write(result); f:close() end
  if active == state then active = nil end
end

function M.start(message, seconds, path)
  if active then finish(active, "cancel") end
  local screen = hs.screen.mainScreen():frame()
  local w, h = 560, 150
  local frame = { x = screen.x + (screen.w - w) / 2, y = screen.y + screen.h * 0.18, w = w, h = h }
  local state = { path = path, left = seconds, done = false }
  local c = hs.canvas.new(frame)
  c:level(hs.canvas.windowLevels.modalPanel)
  c:behavior({ "canJoinAllSpaces", "stationary" })
  c[1] = { type = "rectangle", action = "fill", roundedRectRadii = { xRadius = 14, yRadius = 14 },
           fillColor = { white = 0.08, alpha = 0.92 } }
  c[2] = { type = "text", frame = { x = 24, y = 18, w = w - 48, h = 34 }, text = "Agent",
           textSize = 15, textColor = { white = 0.65 } }
  c[3] = { type = "text", frame = { x = 24, y = 44, w = w - 48, h = 44 }, text = "",
           textSize = 24, textColor = { white = 1 } }
  c[4] = { id = "cancel", type = "rectangle", action = "fill",
           frame = { x = w - 154, y = h - 52, w = 130, h = 36 },
           roundedRectRadii = { xRadius = 8, yRadius = 8 }, fillColor = { red = 0.75, green = 0.2, blue = 0.2 },
           trackMouseUp = true }
  c[5] = { type = "text", frame = { x = w - 154, y = h - 45, w = 130, h = 30 }, text = "Cancel (Esc)",
           textSize = 15, textColor = { white = 1 }, textAlignment = "center" }
  c:mouseCallback(function(_, event, id)
    if id == "cancel" and event == "mouseUp" then finish(state, "cancel") end
  end)
  local function render()
    c[3].text = string.format("%s in %d…", message, state.left)
  end
  render()
  c:show()
  state.canvas = c
  state.esc = hs.hotkey.bind({}, "escape", function() finish(state, "cancel") end)
  state.timer = hs.timer.doEvery(1, function()
    state.left = state.left - 1
    if state.left <= 0 then finish(state, "go") else render() end
  end)
  active = state
  return true
end

function M.cancel()
  if active then finish(active, "cancel") end
end

return M
