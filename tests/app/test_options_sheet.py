"""The Options sheet says what it is, in WebKit: the empty state, a comparison with one Version still rendering, and
what the assistant suggested. Every state names what a tap does, and Pick sends `options.pick`. Live is a FakeLive."""

from __future__ import annotations

import json
import threading

import pytest

from tests.app.test_renders import desk_options, live_value, request, tone  # noqa: F401

from .test_one_option_store import KEY, propose, volume

playwright_sync = pytest.importorskip("playwright.sync_api")

HEADER = "Versions of the mix to compare. Tap one to select it, play it, then Pick the one to keep."
JARGON = ("options.make", "options.pick", "state key", "LOM", "writes", "proposal", "Now")


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def open_sheet(browser, rig, width: int = 390):
    pg = browser.new_context(viewport={"width": width, "height": 844}).new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    commands: list[dict] = []
    pg.on(
        "request",
        lambda r: commands.append(json.loads(r.post_data)) if r.url.endswith("/api/command") and r.post_data else None,
    )
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector(".ctl .w")
    pg.evaluate("S.sheet = 'options'; renderHist()")  # what a tap on the Options tab does
    pg.wait_for_selector("#onow")
    return pg, errors, commands


def sheet_text(pg) -> str:
    return pg.locator("#sheet").inner_text()


def no_jargon(text: str) -> None:
    assert not [w for w in JARGON if w in text], text


def test_the_empty_sheet_says_what_options_are_and_how_to_get_one(rig, browser):
    pg, errors, _ = open_sheet(browser, rig)
    text = sheet_text(pg)
    assert HEADER in text
    assert "Nothing to compare yet." in text and "An Option is a set of versions of your mix" in text
    assert "Ask for a suggestion." in text and "Open the Ask tab" in text
    assert "Render a batch." in text and "Song tab" in text
    assert "off" in pg.get_attribute("#onow", "class")
    no_jargon(text)
    assert errors == []


def test_a_comparison_says_which_version_is_rendering_and_plays_and_picks_one(rig, desk_options, browser):  # noqa: F811
    _, opts, key, ex = desk_options
    second, release = threading.Event(), threading.Event()

    def slow(conn, out, start, length):
        if len(ex.calls) == 1:  # the second render holds
            second.set()
            release.wait(10)
        return ex(conn, out, start, length)

    opts.exporter = slow
    pg, errors, commands = open_sheet(browser, rig)
    opts.make(request(key, 0.6, title="Fader up"))
    assert second.wait(5)
    pg.wait_for_function("document.querySelector('.ol .key.on .tag')?.textContent === 'Rendering version 2 of 2'")
    text = sheet_text(pg)
    assert "Fader up" in text and "Rendered from Live" in text and "Versions appear as they finish" in text
    assert "As it is" in text and "the mix without changes" in text and "Rendering now" in text
    assert "No version selected." in text
    release.set()
    pg.wait_for_function("document.querySelector('.ol .key.on .tag').textContent === '2 versions ready'", timeout=10000)

    pg.click('#vgrid .vc[data-ver="v1"]')
    pg.wait_for_selector("#vgrid .vc.on em.sel")
    text = sheet_text(pg)
    assert "Selected: at 0.6" in text and "Play this version" in text
    assert "louder than As it is" in text or "quieter than As it is" in text
    assert (
        "Pick will set 1 control in Live, at once:" in text
        and "to 0.60" in text
        and "Nothing changes until you tap Pick" in text
    )
    assert key.replace("/", ", ") in text
    assert pg.locator("#onow").inner_text().strip() == 'Pick "at 0.6"'

    pg.click("#oplay")  # the rendered file plays in the page
    pg.wait_for_function("document.querySelector('#oplay').textContent.trim() === 'Stop'")
    assert "/api/options/file?option=" in pg.evaluate("OPT.audio.src")
    pg.click("#oplay")
    pg.wait_for_function("document.querySelector('#oplay').textContent.trim() === 'Play this version'")

    pg.click("#onow")
    pg.wait_for_selector("#odone")
    picks = [c for c in commands if c["kind"] == "options.pick"]
    assert len(picks) == 1 and picks[0]["args"]["version"] == "v1"
    assert live_value(rig, key) == pytest.approx(0.6)
    done = pg.locator("#odone").inner_text()
    assert "Picked. 1 control changed in Live." in done and "Undo takes it back in one step." in done
    assert pg.locator("#vgrid .vc.now em").last.inner_text() == "Picked"
    pg.click("#odone #hundo")
    pg.wait_for_selector("#odone", state="detached")
    assert live_value(rig, key) != pytest.approx(0.6)

    pg.click('#vgrid .vc[data-ver="base"]')  # the mix without changes holds nothing to pick
    pg.wait_for_selector("#onot")
    assert "There is nothing to pick." in pg.locator("#onot").inner_text()
    no_jargon(sheet_text(pg))
    assert errors == []


def test_a_suggestion_shows_its_reason_and_its_changes_before_the_pick(asked, browser):
    rig = asked.rig
    oid = propose(asked)
    before = volume(rig)
    pg, errors, commands = open_sheet(browser, rig)
    text = sheet_text(pg)
    assert HEADER in text and "Kick down" in text and "Suggestion, not applied yet" in text
    assert "Suggested by the assistant in Ask." in text and "Why: It masks the bass." in text
    assert "Nothing has changed on the mix yet." in text
    assert "The suggestion: Kick down" in text and "there is nothing to play here" in text
    assert pg.locator("#vgrid").count() == 0  # one suggestion is not a grid of versions
    will = pg.locator("#owill").inner_text()
    assert "Pick will set 1 control in Live, at once:" in will and "Kick bus, volume" in will
    assert f"from {before:.2f} to 0.30" in will and "dB now)" in will
    no_jargon(text)
    assert volume(rig) == pytest.approx(before)

    pg.click("#onow")
    pg.wait_for_selector("#odone")
    assert [c["args"] for c in commands if c["kind"] == "options.pick"] == [{"option": oid, "version": "v1"}]
    assert volume(rig) == pytest.approx(0.3)
    pg.wait_for_function("document.querySelector('.ol .key.on .tag').textContent === 'Suggestion, picked'")
    assert "You picked it." in sheet_text(pg)
    assert errors == []


def test_a_suggestion_with_text_values_says_why_it_cannot_be_picked(asked, browser):
    propose(asked, {"title": "Kick -6", "why": "Too loud.", "moves": [{"target": KEY, "to": "-6 dB"}]})
    pg, errors, commands = open_sheet(browser, asked.rig)
    assert "off" in pg.get_attribute("#onow", "class")
    assert "gives its values as text" in pg.locator("#onot").inner_text()
    pg.click("#onow")
    assert not [c for c in commands if c["kind"] == "options.pick"]
    assert errors == []


def test_the_side_column_names_the_comparison_on_a_desktop(asked, browser):
    propose(asked)
    pg, errors, _ = open_sheet(browser, asked.rig, 1280)
    side = pg.locator("#side").inner_text()
    assert "VERSIONS TO COMPARE" in side.upper() and "Kick down" in side and "open Options to play or Pick it" in side
    assert errors == []
