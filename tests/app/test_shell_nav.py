"""The /app/ shell in WebKit, on FakeLive: the one tab bar at every width, the hash routes, and a page change that
shows it is waiting until Live confirms it. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import threading

import pytest

from zpkt.live.transport import LiveError

playwright_sync = pytest.importorskip("playwright.sync_api")

TABS = """() => [...document.querySelectorAll('#tabs > *')].map(e => { const r = e.getBoundingClientRect();
  return {t: e.dataset.t, text: e.textContent.trim(), tag: e.tagName, on: e.classList.contains('on'),
          w: Math.round(r.width), h: Math.round(r.height), inside: r.left >= 0 && r.right <= innerWidth + 0.5,
          href: e.getAttribute('href')}; })"""
PENDING = """() => ({waiting: [...document.querySelectorAll('button.is-waiting')].map(b => b.dataset.page),
  loading: document.querySelector('#main').classList.contains('is-loading'),
  dimmed: document.querySelector('#main').classList.contains('is-pending'),
  opacity: +getComputedStyle(document.querySelector('#desk [data-stale]')).opacity,
  line: getComputedStyle(document.querySelector('#main'), '::before').opacity,
  page: zpkt.S.state.page, slow: document.querySelector('#slow').hidden ? '' : document.querySelector('#slow').innerText})"""


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def open_app(browser, rig, width: int = 390, path: str = "/app/"):
    pg = browser.new_page(viewport={"width": width, "height": 800})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + path)
    pg.wait_for_selector("#kplay")  # the first state has come
    pg.wait_for_function("document.querySelectorAll('.ctl .w, .pc .w, #song > *').length > 0")
    return pg, errors


class SlowPager:
    """The desk's calls into Live, with every page change held until `go` is set (or failing while `fail` is)."""

    def __init__(self, desk, monkeypatch):
        self.go, self.fail, real = threading.Event(), False, desk.call

        def call(code, *args, **kwargs):
            if "DESK.arm(" in code:
                if self.fail:
                    raise LiveError("Live is busy")
                self.go.wait(10)
            return real(code, *args, **kwargs)

        monkeypatch.setattr(desk, "call", call)


@pytest.mark.parametrize("width", [375, 1280])
def test_the_tab_bar_shows_its_three_tabs_and_no_options(browser, rig, width):
    pg, errors = open_app(browser, rig, width)
    tabs = pg.evaluate(TABS)
    assert [t["text"] for t in tabs] == ["Desk", "Song", "Ask"]
    assert all(t["inside"] and t["w"] >= 44 and t["h"] >= 44 for t in tabs), tabs
    assert [t["t"] for t in tabs if t["on"]] == ["desk"]
    assert all(t["tag"] == "BUTTON" for t in tabs)  # all three switch in place, Ask too
    assert "Options" not in pg.inner_text("body") and pg.locator("#topts, #sopts, [data-t=options]").count() == 0
    assert pg.locator("#sask").count() == 0  # no stray Ask button
    assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    # the bar is at the bottom on a phone and at the top on a desktop
    box = pg.locator("#tabs").bounding_box()
    assert (box["y"] < 10) if width >= 700 else (box["y"] + box["height"] > 790)
    assert errors == []


def test_the_tabs_switch_in_place_and_the_address_follows(browser, rig):
    pg, errors = open_app(browser, rig, 375)
    pg.click("#tabs [data-t=song]")
    assert pg.locator("#song").is_visible() and pg.locator("#desk").is_hidden()
    assert pg.evaluate("location.hash") == "#song"
    pg.click("#tabs [data-t=desk]")
    assert pg.locator("#desk").is_visible() and pg.evaluate("location.hash") == "#desk"
    assert "on" not in (pg.locator("#sheet").get_attribute("class") or "").split()
    assert errors == []


@pytest.mark.parametrize(("hash_", "want"), [("#song", "song"), ("#options", "desk"), ("#desk", "desk")])
def test_a_hash_opens_its_tab_on_load(browser, rig, hash_, want):
    pg, errors = open_app(browser, rig, 375, "/app/" + hash_)
    assert [t["t"] for t in pg.evaluate(TABS) if t["on"]] == [want]
    assert pg.locator("#song").is_visible() == (want == "song")
    assert pg.locator("#sheet.on").count() == 0
    assert pg.evaluate("location.hash") == "#" + want  # an old link to the Options tab lands on the Desk
    assert errors == []


def test_a_page_change_shows_it_is_waiting_then_clears(browser, rig, monkeypatch):
    slow = SlowPager(rig.desk, monkeypatch)
    pg, errors = open_app(browser, rig, 1280)  # a desktop: the Pages list and the dots' twin
    assert pg.evaluate(PENDING)["waiting"] == []
    was = pg.locator("#pagename").inner_text()
    pg.click('#side button[data-page="1"]')
    got = pg.evaluate(PENDING)  # at once: Live has not answered
    assert got["waiting"] and set(got["waiting"]) == {"1"}
    assert got["loading"] and got["dimmed"] and got["line"] == "1" and got["page"] == 0
    assert pg.locator("#main").get_attribute("aria-busy") == "true"
    # the new page's name shows at once, with "Loading" beside it; its button in the list is the marked one
    want = pg.locator('#side button[data-page="1"]').inner_text()
    assert pg.locator("#pagename").inner_text() == want != was
    assert pg.locator("#pgwait").inner_text() == "Loading"
    assert "on" in pg.locator('#side button[data-page="1"]').get_attribute("class").split()
    pg.wait_for_function("+getComputedStyle(document.querySelector('#desk [data-stale]')).opacity < 0.5")
    slow.go.set()
    pg.wait_for_function("zpkt.S.state.page === 1 && !zpkt.S.pend")
    got = pg.evaluate(PENDING)
    assert got == {**got, "waiting": [], "loading": False, "dimmed": False, "line": "0", "slow": ""}
    assert pg.locator("#pagename").inner_text() != was and pg.locator("#pgwait").count() == 0
    pg.wait_for_function("+getComputedStyle(document.querySelector('#desk [data-stale]')).opacity === 1")
    assert errors == []


def test_a_page_that_does_not_change_says_so_and_retry_works(browser, rig, monkeypatch):
    slow = SlowPager(rig.desk, monkeypatch)
    pg, errors = open_app(browser, rig, 375)
    pg.evaluate("zpkt.wait.page = 150")  # the real wait is 5 s
    pg.click('.dots button[data-page="1"]')
    assert pg.evaluate(PENDING)["waiting"] == ["1"]
    pg.wait_for_selector("#slowretry")
    got = pg.evaluate(PENDING)
    assert got["slow"].startswith("The page did not change.") and not got["loading"] and not got["dimmed"]
    assert pg.locator("#pgwait").count() == 0  # the name is the page Live still has
    assert pg.locator("#slowretry").bounding_box()["height"] >= 44
    slow.go.set()  # the answer comes late: the message goes away
    pg.wait_for_function("zpkt.S.state.page === 1 && document.querySelector('#slow').hidden")
    # Live refuses: the message comes at once, and Retry sends it again
    slow.fail = True
    pg.click('.dots button[data-page="0"]')
    pg.wait_for_selector("#slowretry")
    assert "Live is busy" in pg.locator("#slow").inner_text() and pg.evaluate("zpkt.S.state.page") == 1
    slow.fail = False
    pg.click("#slowretry")
    pg.wait_for_function("zpkt.S.state.page === 0 && document.querySelector('#slow').hidden && !zpkt.S.pend")
    assert errors == []


def test_a_page_hash_opens_the_desk_on_that_saved_page(browser, rig):
    spec = {"title": "Kick only", "groups": [{"name": "Bus", "controls": [{"target": "Kick bus/volume"}]}]}
    code, reply = rig.command("page.make", {"spec": spec})
    assert code == 200, reply
    pid = reply["id"]
    rig.command("page.arm", {"page": 0})
    pg, errors = open_app(browser, rig, 375, f"/app/#page={pid}")
    pg.wait_for_function("document.querySelector('#pagename')?.textContent === 'Kick only'")
    assert pg.evaluate("location.hash") == "#desk"
    pg.evaluate("location.hash = '#page=no-such-page'")
    pg.wait_for_selector("#slow:not([hidden])")
    assert "not on the desk" in pg.locator("#slow").inner_text()
    assert errors == []


def test_reduced_motion_stills_the_line(browser, rig, monkeypatch):
    SlowPager(rig.desk, monkeypatch)
    pg = browser.new_page(viewport={"width": 375, "height": 800}, reduced_motion="reduce")
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector(".ctl .w")
    pg.click('.dots button[data-page="1"]')
    got = pg.evaluate(
        """() => { const s = getComputedStyle(document.querySelector('#main'), '::before'),
                       b = getComputedStyle(document.querySelector('button.is-waiting'));
                   return [s.animationName, s.opacity, b.animationName]; }"""
    )
    assert got == ["none", "1", "none"]
