-- Pins hs.execute behavior for an osascript call.
return function(t)
  local out, ok = hs.execute('osascript -e "return 42"')
  t.eq(ok, true, "osascript exit 0 -> ok is true")
  t.isType(out, "string", "stdout is a string")
  t.ok(out:match("42"), "stdout contains the returned value")
end
