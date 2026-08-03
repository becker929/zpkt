local blocklist = require("core.blocklist")

describe("blocklist.isMusicApp", function()
  it("returns true when bundleID matches", function()
    assert.is_true(blocklist.isMusicApp("com.ableton.live", "com.ableton.live"))
  end)
  it("returns false when bundleID differs", function()
    assert.is_false(blocklist.isMusicApp("com.slack.foo", "com.ableton.live"))
  end)
  it("returns false for empty string", function()
    assert.is_false(blocklist.isMusicApp("", "com.ableton.live"))
  end)
end)

describe("blocklist.isBlocklisted", function()
  local list = {
    { name = "Slack",   bundleID = "com.tinyspeck.slackmacgap" },
    { name = "Discord", bundleID = "com.hnc.Discord" },
  }

  it("returns true for a matching entry", function()
    assert.is_true(blocklist.isBlocklisted("com.tinyspeck.slackmacgap", list))
  end)
  it("returns true for a second matching entry", function()
    assert.is_true(blocklist.isBlocklisted("com.hnc.Discord", list))
  end)
  it("returns false for a non-matching entry", function()
    assert.is_false(blocklist.isBlocklisted("com.apple.safari", list))
  end)
  it("returns false for an empty list", function()
    assert.is_false(blocklist.isBlocklisted("com.tinyspeck.slackmacgap", {}))
  end)
end)
