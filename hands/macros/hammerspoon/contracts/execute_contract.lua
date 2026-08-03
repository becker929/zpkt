-- Pins the REAL behavior of hs.execute vs what the docs claim.
-- The original 2026 bug: code compared the 3rd return to 0 (a number).
-- The 3rd return is actually the string "exit" or "signal".
return function(t)
  local _, ok, kind, code = hs.execute("exit 3")
  t.eq(ok, nil, "non-zero exit -> 2nd return is nil (NOT false — nil is the falsy sentinel)")
  t.isType(kind, "string", "3rd return is a STRING, not a number (docs are wrong)")
  t.eq(kind, "exit", "3rd return is 'exit' for a normal process exit")
  t.isType(code, "number", "4th return is the numeric exit code")
  t.eq(code, 3, "4th return equals the exit code value")

  local _, ok2, kind2, code2 = hs.execute("true")
  t.eq(ok2, true, "exit 0 -> 2nd return is true")
  t.eq(kind2, "exit", "successful command also reports 'exit'")
  t.eq(code2, 0, "successful command exit code is 0")
end
