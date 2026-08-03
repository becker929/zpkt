return {
  musicApp = {
    name     = "Ableton Live 12 Suite",
    bundleID = "com.ableton.live",
  },

  -- Apps that will be QUIT (not minimized) during workspace activation.
  -- Restore will relaunch them best-effort.
  blocklist = {
    { name = "Slack",   bundleID = "com.tinyspeck.slackmacgap" },
    { name = "Discord", bundleID = "com.hnc.Discord" },
  },

  hotkeys = {
    activate = { mods = {"ctrl", "alt", "cmd"}, key = "m" },
  },
}
