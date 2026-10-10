-- The zpkt `hands` CLI: Live control over the AbletonLiveMCP remote script.
local handsBin = os.getenv("HOME") .. "/Desktop/zpkt/hands/.venv/bin/hands"

return {
  handsBin = handsBin,

  musicApp = {
    name     = "Ableton Live 12 Suite",
    bundleID = "com.ableton.live",
  },

  rendersDir = "/Users/anthonybecker/_renders",

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
    projectsDir     = "/Users/anthonybecker/_music_projects",
    backupsDir      = "/Users/anthonybecker/Library/Mobile Documents/com~apple~CloudDocs/Ableton Backups",
    cloneDir        = "/Users/anthonybecker/Library/Mobile Documents/com~apple~CloudDocs/_music_projects",
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
