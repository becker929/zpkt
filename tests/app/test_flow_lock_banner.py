"""The red bar of the /app/ shell when Live cannot be reached, in WebKit: it shows Live's status and goes away when
Live is back. The messages are the ones the server's event stream sends, handed to the page's own `apply`.
(The wrong-set refusal is a 409 to the command and has no banner of its own on the page, so there is none to test.)"""

from __future__ import annotations

from tests.app.test_flows import page  # noqa: F401  (the fixture: the real page on the app over FakeLive)


def test_the_lock_bar_names_live_s_status_and_clears_when_live_returns(page):  # noqa: F811
    assert not page.locator("#lock").is_visible()
    page.evaluate("apply({t: 'full', state: {...S.state, live: 'unreachable'}})")
    assert page.locator("#lock").is_visible()
    assert page.locator("#lock").inner_text() == "Live: unreachable"
    page.evaluate("apply({t: 'full', state: {...S.state, live: 'attached'}})")
    assert not page.locator("#lock").is_visible()


def test_a_lost_event_stream_says_so(page):  # noqa: F811
    page.evaluate("S.lockReason = 'Lost the connection. Trying again.'; renderHear()")
    assert page.locator("#lock").inner_text() == "Lost the connection. Trying again."
    assert page.locator("#lock").is_visible()
