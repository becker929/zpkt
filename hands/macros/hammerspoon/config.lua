return {
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
}
