-- A/B the mix against reference tracks, and show Live's master Spectrum.
-- Each hotkey runs the `hands` CLI (hands/src/hands/ab.py), which talks to
-- Live through the AbletonLiveMCP remote script on 127.0.0.1:16619.
-- Reference tracks are audio tracks named "REF <name>".

local M = {}

local function describe(res)
  local parts = {}
  if res.mode == "ref" then
    table.insert(parts, "▶ " .. tostring(res.ref))
  elseif res.mode == "mix" then
    table.insert(parts, "▶ mix")
  end
  if res.spectrum == true then
    table.insert(parts, "spectrum on")
  elseif res.spectrum == false then
    table.insert(parts, "spectrum off")
  end
  return table.concat(parts, " · ")
end

local function run(bin, args)
  hs.task.new(bin, function(code, out, err)
    local ok, res = pcall(hs.json.decode, out or "")
    if code ~= 0 or not ok or type(res) ~= "table" then
      local msg = (err ~= nil and err ~= "") and err or (out or "no answer")
      hs.alert.show("A/B: " .. msg:sub(1, 120))
      return
    end
    hs.alert.show(describe(res), 0.8)
  end, args):start()
end

---@param cfg table { bin, toggle, toggleSpectrum, spectrum, next } with {mods, key} per hotkey
function M.bind(cfg)
  local actions = {
    toggle         = { "ab", "toggle" },
    toggleSpectrum = { "ab", "toggle", "--spectrum" },
    spectrum       = { "spectrum" },
    next           = { "ab", "next" },
  }
  for name, args in pairs(actions) do
    local hk = cfg[name]
    if hk then
      hs.hotkey.bind(hk.mods, hk.key, function() run(cfg.bin, args) end)
    end
  end
end

M._describe = describe -- for tests

return M
