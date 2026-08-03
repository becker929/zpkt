local M = {}

--- Sends the Ableton Save-As key sequence and types the given filename.
--- continuation() is called when the sequence is complete.
function M.saveAs(app, fname, continuation)
  app:activate()
  hs.timer.doAfter(0.4, function()
    hs.eventtap.keyStroke({"cmd","shift"}, "s")
    hs.timer.doAfter(0.6, function()
      hs.eventtap.keyStroke({"cmd"}, "a")
      hs.timer.doAfter(0.1, function()
        hs.eventtap.keyStrokes(fname)
        hs.timer.doAfter(0.1, function()
          hs.eventtap.keyStroke({}, "return")
          hs.timer.doAfter(1.2, continuation)
        end)
      end)
    end)
  end)
end

return M
