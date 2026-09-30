local M = {}

-- Time to let the Cmd+S keystroke actually reach the app before we switch
-- focus away again; switching immediately risks the synthetic keystroke
-- landing after focus has already moved.
local SAVE_KEY_SETTLE_SECONDS = 0.15

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

--- Sends Cmd+S to save the current project in place.
--- onSaved() (optional) is invoked shortly after the keystroke is sent —
--- e.g. to restore focus to whatever was focused before, without waiting
--- for the save itself to finish writing to disk.
--- continuation() is called after the save completes.
function M.save(app, continuation, onSaved)
  app:activate()
  hs.timer.doAfter(0.4, function()
    hs.eventtap.keyStroke({"cmd"}, "s")
    if onSaved then
      hs.timer.doAfter(SAVE_KEY_SETTLE_SECONDS, onSaved)
    end
    hs.timer.doAfter(2.0, continuation)
  end)
end

return M
