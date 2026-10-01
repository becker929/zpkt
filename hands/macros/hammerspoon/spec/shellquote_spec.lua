local q = require("core.shellquote").quote

describe("shellquote.quote", function()
  it("wraps plain text in single quotes", function()
    assert.are.equal("'a b'", q("a b"))
  end)

  it("neutralises command substitution and backticks", function()
    assert.are.equal("'$(rm -rf ~)'", q("$(rm -rf ~)"))
    assert.are.equal("'`id`'", q("`id`"))
  end)

  it("escapes embedded single quotes", function()
    assert.are.equal([['it'\''s']], q("it's"))
  end)

  it("round-trips through a real shell", function()
    for _, s in ipairs({ "plain", "a b", "$(echo pwned)", "`id`", "it's", 'q"q', "x;y|z&w" }) do
      local p = io.popen("printf %s " .. q(s))
      local out = p:read("*a"); p:close()
      assert.are.equal(s, out)
    end
  end)
end)
