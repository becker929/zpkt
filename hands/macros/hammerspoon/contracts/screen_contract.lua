-- Confirms frame() excludes menu bar / Dock (the value we use for resize target).
return function(t)
  local main = hs.screen.mainScreen()
  t.ok(main, "mainScreen() returns a screen")
  local f = main:frame()
  local ff = main:fullFrame()
  t.ok(f.h < ff.h or f.y > ff.y, "frame() is smaller/offset vs fullFrame()")
end
