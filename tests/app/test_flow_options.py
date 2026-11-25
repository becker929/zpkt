"""Flow 7 in WebKit: the Options sheet. Older tools' Options are listed, a Version goes on the Hear bar with its
numbers, a new job streams "rendering 2 of 3", and a Version is made Now. Live is a FakeLive; the export is a fake."""

from __future__ import annotations

import threading

import pytest

from tests.app.test_renders import arranger, desk_options, live_value, request, tone  # noqa: F401
from zpkt.app import renders

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def phone(rig):
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(rig.url + "/app/")
        pg.wait_for_selector(".ctl .w")
        yield pg
        browser.close()
    assert errors == []


def test_older_options_are_listed_and_a_version_goes_on_the_hear_bar(rig, arranger, phone):  # noqa: F811
    phone.click("#topts")
    phone.wait_for_selector("#vgrid .vc")
    assert phone.locator(".ol .key").count() == 2
    phone.locator('.ol .key:has-text("Spectral")').click()
    phone.click('#vgrid .vc[data-ver="before"]')
    phone.wait_for_selector("#vstrip")
    text = phone.locator("#vstrip").inner_text()
    assert "Before" in text and "LUFS" in text
    phone.wait_for_selector(".spc.ver i")
    assert phone.locator(".spc.ver i").count() == 31
    overflow = phone.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow == 0


def test_a_new_job_streams_its_progress_and_a_version_is_made_now(rig, desk_options, phone):  # noqa: F811
    _, opts, key, ex = desk_options
    second, release = threading.Event(), threading.Event()

    def slow(conn, out, start, length):
        if len(ex.calls) == 1:  # the second render holds
            second.set()
            release.wait(10)
        return ex(conn, out, start, length)

    opts.exporter = slow
    phone.click("#topts")
    opts.make(request(key, 0.3, 0.6))
    assert second.wait(5)
    phone.wait_for_function("document.querySelector('.ol .key.on .tag').textContent === 'rendering 2 of 3'")
    release.set()
    phone.wait_for_function("document.querySelector('.ol .key.on .tag').textContent === 'ready'", timeout=10000)
    phone.click('#vgrid .vc[data-ver="v2"]')
    phone.wait_for_selector("#vstrip")
    assert "gap" in phone.locator("#vstrip").inner_text()
    phone.click("#onow")
    phone.wait_for_selector("#vgrid .vc.now")
    assert live_value(rig, key) == pytest.approx(0.6)
    assert renders.CLAIM_WAIT_S > 0
