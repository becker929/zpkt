local M = {}

local function newT(results, suite)
  local function record(ok, msg, detail)
    results[#results+1] = { suite=suite, ok=ok, msg=msg, detail=detail }
  end
  return {
    eq = function(got, want, msg)
      local pass = (got == want)
      record(pass, msg or "eq",
        pass and nil or ("expected "..tostring(want).." got "..tostring(got)))
    end,
    isType = function(got, want, msg)
      local pass = (type(got) == want)
      record(pass, msg or "isType",
        pass and nil or ("expected type "..want.." got "..type(got)))
    end,
    ok = function(val, msg)
      record(val and true or false, msg or "ok",
        val and nil or "expected truthy")
    end,
  }
end

function M.run()
  local dir = hs.configdir .. "/contracts"
  local results = {}

  for file in hs.fs.dir(dir) do
    local suite = file:match("^(.+)_contract%.lua$")
    if suite then
      local modname = "contracts." .. suite .. "_contract"
      local ok, mod = pcall(require, modname)
      if not ok then
        results[#results+1] = { suite=suite, ok=false, msg="load", detail=tostring(mod) }
      else
        local t = newT(results, suite)
        local runok, err = pcall(mod, t)
        if not runok then
          results[#results+1] = { suite=suite, ok=false, msg="crash", detail=tostring(err) }
        end
      end
    end
  end

  local passed, failed = 0, 0
  for _, r in ipairs(results) do
    if r.ok then passed = passed + 1 else failed = failed + 1 end
  end
  return { passed=passed, failed=failed, results=results }
end

return M
