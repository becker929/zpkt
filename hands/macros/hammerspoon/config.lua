-- Paths on this Mac. ZPKT_HOME names the clone (default ~/Desktop/zpkt).
local HOME = os.getenv("HOME")
local ZPKT = os.getenv("ZPKT_HOME") or (HOME .. "/Desktop/zpkt")
-- The zpkt `hands` CLI: Live control over the AbletonLiveMCP remote script.
local handsBin = ZPKT .. "/hands/.venv/bin/hands"

return {
  handsBin = handsBin,

  musicApp = {
    name     = "Ableton Live 12 Suite",
    bundleID = "com.ableton.live",
  },

  rendersDir = HOME .. "/_renders",

  -- Apps that will be QUIT (not minimized) during workspace activation.
  -- Restore will relaunch them best-effort.
  blocklist = {
    { name = "Slack",   bundleID = "com.tinyspeck.slackmacgap" },
    { name = "Discord", bundleID = "com.hnc.Discord" },
  },

  autoBackup = {
    intervalMinutes = 5,
    idleSeconds     = 120,
    maxVersions     = 5,
    projectsDir     = HOME .. "/_music_projects",
    backupsDir      = HOME .. "/Library/Mobile Documents/com~apple~CloudDocs/Ableton Backups",
    cloneDir        = HOME .. "/Library/Mobile Documents/com~apple~CloudDocs/_music_projects",
  },

  hotkeys = {
    activate = { mods = {"ctrl", "alt", "cmd"}, key = "m" },
  },

  -- A/B against "REF ..." tracks and the master Spectrum (modules/ab-hotkeys.lua).
  ab = {
    bin            = handsBin,
    toggle         = { mods = {"ctrl", "alt", "cmd"}, key = "a" },  -- mix <-> reference
    toggleSpectrum = { mods = {"ctrl", "alt", "cmd"}, key = "d" },  -- A/B and show Spectrum
    spectrum       = { mods = {"ctrl", "alt", "cmd"}, key = "s" },  -- Spectrum on/off
    next           = { mods = {"ctrl", "alt", "cmd"}, key = "n" },  -- next reference
  },
}
