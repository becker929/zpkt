"""The page in a browser against the in-process server (conftest.py's rig): it renders the state Live reports and
sends what is clicked. Needs Playwright and its Chromium; without them it skips:

    cd hands && uv run --all-extras --with playwright python -m pytest ../contrib/mixdesk/tests/test_page.py
    (once: uv run --with playwright playwright install chromium)
"""

from __future__ import annotations

import pytest
from conftest import wait_for

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def page(rig):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--mute-audio"])
        except sync_api.Error as exc:
            pytest.skip(f"no Chromium for Playwright ({str(exc).splitlines()[0]})")
        pg = browser.new_page(viewport={"width": 1200, "height": 800})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(f"{e} {e.stack}"))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(rig.url + "/desk/")
        yield pg, errors
        browser.close()


def test_the_page_paints_the_state_and_follows_live(rig, page):
    pg, errors = page
    pg.wait_for_function("document.getElementById('status').textContent.includes('Live')")
    assert pg.locator('.ctl .val[title="-6.00 dB"]').count() >= 1  # page 0 k8: Main's headroom
    rig.live.run("find_track('Perc bus').mixer_device.volume.value = 0.5")  # page 0 k1, from anywhere
    pg.wait_for_function("[...document.querySelectorAll('.ctl .val')].some((v) => v.title === '-14.0 dB')")
    assert pg.locator("#abc button").count() == 4  # A, B, W, C from the analysis
    # the server's loudness match: A's drop (-9 LUFS) comes down to the quietest of A, B and C1 (-12)
    pg.wait_for_function("document.querySelector('#abc button').textContent.includes('-3.0')")
    assert errors == []


def test_the_page_arms_a_page_and_flips_a_pad(rig, page):
    pg, errors = page
    pg.wait_for_function("document.getElementById('status').textContent.includes('Live')")
    pg.select_option("#pagesel", "2")
    assert wait_for(lambda: rig.call("m.DESK.page") == 2)
    desk = rig.get("/api/desk")[1]
    page_i, slot = next(
        (i, s)
        for i, p in enumerate(desk["pages"])
        for s, c in p["controls"].items()
        if s.startswith("b") and c.get("param") == "mute"
    )
    track = rig.track(desk["pages"][page_i]["controls"][slot]["track"])
    was = track.mute
    pg.select_option("#pagesel", str(page_i))
    pg.locator(".card").nth(page_i).locator(".ctl.padb").nth(int(slot[1:]) - 1).click()
    assert wait_for(lambda: track.mute is (not was))
    assert errors == []
