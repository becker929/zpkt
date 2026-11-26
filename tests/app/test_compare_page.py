"""Compare states on the Desk in /app/ (WebKit, on FakeLive): a press lights its pad and moves the knobs before Live
has answered, writes once, and one undo takes it back; a knob turned afterwards puts every pad out; the MiniLab's pad
shows on the screen; an agent's update changes the panel in place; and there are three tabs and no Options at 375 and
1200 px. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import json
import threading

import pytest

from tests.app.conftest import wait_for
from zpkt.app import agent_commands
from zpkt.app.bus import Command

playwright_sync = pytest.importorskip("playwright.sync_api")

VOL, GAIN, WET = "Kick bus/volume", "Kick bus/desk EQ/1 Gain A", "Kick bus/desk Glue/Dry/Wet"
SPEC = {
    "title": "Kick: hotter?",
    "groups": [{"name": "Kick", "controls": [{"target": VOL, "label": "Level"}, {"target": GAIN, "label": "Sub"}]}],
    "compare": {
        "name": "Kick",
        "states": [
            {"name": "as it is"},
            {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}, {"target": GAIN, "to": 0.7}]},
            {"name": "drier", "writes": [{"target": WET, "to": 0.2}]},
        ],
    },
}


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


@pytest.fixture()
def rig(rig):
    agent_commands.register(rig.desk.bus, rig.desk)
    return rig


def open_page(browser, rig, width=1200, height=800, scheme="light"):
    code, reply = rig.desk.bus.submit(Command("page.draft", "agent", {"spec": SPEC}))
    assert code == 200, reply
    pg = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"{rig.url}/app/#page={reply['id']}")  # the link the agent gave: opening it is the person's act
    pg.wait_for_function("document.querySelector('#pagename')?.textContent === 'Kick: hotter?'")
    pg.wait_for_selector("#panel .mc.pad.cmp.on")
    pg.errors = errors  # type: ignore[attr-defined]
    pg.page_id = reply["id"]  # type: ignore[attr-defined]
    return pg


def pad(name: str) -> str:
    return f'#panel .mc.pad.cmp:has(button[aria-label="Kick: {name}"])'


def lit(pg) -> list[str]:
    return pg.evaluate("[...document.querySelectorAll('#panel .mc.pad.cmp.on')].map(e => e.innerText.trim())")


def place(pg, key) -> float:
    return float(pg.locator(f'#panel .mc[data-key="{key}"]').get_attribute("data-n"))


def raw(rig, key):
    return (rig.desk.history.value(key) or [None, None])[1]


class Held:
    """Live, made to wait: every write to it blocks until `go` is set, and each one is counted."""

    def __init__(self, desk, monkeypatch):
        self.go, self.writes = threading.Event(), []
        real = desk.write

        def write(pairs):
            self.writes.append(pairs)
            self.go.wait(10)
            return real(pairs)

        monkeypatch.setattr(desk, "write", write)


def test_a_press_lights_the_pad_and_moves_the_knobs_at_once_and_writes_once(browser, rig, monkeypatch):
    pg = open_page(browser, rig)
    assert lit(pg) == ["as it is"]  # the mix is as it was when the page was made
    base_vol, base_gain = place(pg, VOL), place(pg, GAIN)
    held = Held(rig.desk, monkeypatch)
    pg.click(pad("hotter") + " button")
    # before Live has taken anything: the pad is lit, the other is out, and both knobs stand at the state's values
    pg.wait_for_function("document.querySelector('#panel .mc.pad.cmp.on')?.innerText.trim() === 'hotter'", timeout=1000)
    assert lit(pg) == ["hotter"]
    assert place(pg, VOL) == pytest.approx(0.8, abs=1e-3) and place(pg, GAIN) != pytest.approx(base_gain)
    assert pg.locator(f'#panel .mc[data-key="{VOL}"]').evaluate("e => e.classList.contains('sending')")
    assert raw(rig, VOL) != pytest.approx(0.8) or held.writes  # Live itself has not moved yet
    assert pg.locator(pad("hotter") + " button").get_attribute("aria-pressed") == "true"
    held.go.set()
    pg.wait_for_function(f"!window.zpkt.own[{json.dumps(VOL)}] && !window.zpkt.own[{json.dumps(GAIN)}]")
    assert len(held.writes) == 1 and {p[0] for p in held.writes[0]} == {VOL, GAIN, WET}  # one command, every target
    assert lit(pg) == ["hotter"] and place(pg, VOL) == pytest.approx(0.8, abs=1e-3)  # Live agrees: nothing flashes back
    # History has one row for the switch, named for it
    pg.click("#khist")
    row = pg.locator("#hrows .he").first.inner_text()
    assert "Kick" in row and "as it is → hotter" in row and "2 controls" in row
    pg.click("#hclose")
    # one undo takes the whole switch back, and the first pad is lit again
    pg.click("#kundo")
    pg.wait_for_function("document.querySelector('#panel .mc.pad.cmp.on')?.innerText.trim() === 'as it is'")
    assert place(pg, VOL) == pytest.approx(base_vol, abs=1e-3) and place(pg, GAIN) == pytest.approx(base_gain, abs=1e-3)
    assert len(held.writes) == 2
    assert pg.errors == []


def test_a_knob_turned_afterwards_puts_every_pad_out(browser, rig):
    pg = open_page(browser, rig)
    pg.click(pad("hotter") + " button")
    pg.wait_for_function(f"!window.zpkt.own[{json.dumps(VOL)}]")
    assert lit(pg) == ["hotter"]
    knob = pg.locator(f'#panel .mc[data-key="{VOL}"] .w')
    knob.focus()
    pg.keyboard.press("ArrowDown")  # a hundredth of its range
    pg.wait_for_function("document.querySelectorAll('#panel .mc.pad.cmp.on').length === 0", timeout=1000)
    assert lit(pg) == []
    assert all(
        v == "false"
        for v in pg.evaluate(
            "[...document.querySelectorAll('#panel .mc.pad.cmp button')].map(b => b.getAttribute('aria-pressed'))"
        )
    )
    pg.keyboard.press("ArrowUp")  # back to the state's value by hand: its pad is lit again, nothing was stored
    pg.wait_for_function("document.querySelector('#panel .mc.pad.cmp.on')?.innerText.trim() === 'hotter'")
    # a state whose values no knob of the page shows still lights and switches
    pg.click(pad("drier") + " button")
    pg.wait_for_function("document.querySelector('#panel .mc.pad.cmp.on')?.innerText.trim() === 'drier'")
    assert wait_for(lambda: raw(rig, WET) == pytest.approx(0.2))
    assert pg.errors == []


def test_the_minilabs_pad_shows_on_the_screen(browser, rig):
    pg = open_page(browser, rig)
    rig.minilab.elements.pad_bank_a_raw[6].receive(127)  # pad 7 holds "hotter"
    pg.wait_for_function("document.querySelector('#panel .mc.pad.cmp.on')?.innerText.trim() === 'hotter'")
    assert place(pg, VOL) == pytest.approx(0.8, abs=1e-3)
    pg.click("#khist")
    row = pg.locator("#hrows .he").first
    assert "as it is → hotter" in row.inner_text() and row.locator(".who").inner_text() == "minilab"
    assert pg.errors == []


def test_an_agents_update_changes_the_panel_in_place(browser, rig):
    pg = open_page(browser, rig)
    brighter = json.loads(json.dumps(SPEC))
    brighter["id"] = pg.page_id
    brighter["compare"]["states"][2] = {"name": "brighter", "writes": [{"target": GAIN, "to": 0.95}]}
    code, reply = rig.desk.bus.submit(Command("page.draft", "agent", {"spec": brighter}))
    assert code == 200 and reply["updated"]
    pg.wait_for_selector(pad("brighter"))  # no reload, no new page: the same panel has the new state
    assert pg.locator(pad("drier")).count() == 0
    assert pg.locator("#pagename").inner_text() == "Kick: hotter?"
    assert lit(pg) == ["as it is"]  # the update moved nothing
    pg.click(pad("brighter") + " button")
    assert wait_for(lambda: raw(rig, GAIN) == pytest.approx(0.95))  # the person's press moves the mix
    assert pg.errors == []


@pytest.mark.parametrize(("width", "height", "scheme"), [(375, 812, "light"), (375, 812, "dark"), (1200, 800, "light")])
def test_the_pads_fit_a_thumb_and_the_page_has_three_tabs_and_no_options(browser, rig, width, height, scheme):
    pg = open_page(browser, rig, width, height, scheme)
    tabs = pg.evaluate("[...document.querySelectorAll('#tabs > *')].map(e => e.innerText.trim())")
    assert tabs == ["Desk", "Song", "Ask"]
    assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0  # nothing scrolls sideways
    for name in ("as it is", "hotter", "drier"):
        box = pg.locator(pad(name) + " button").bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44, (name, box)
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        assert box["y"] >= 0 and box["y"] + box["height"] <= height, "the pads are in sight when the page opens"
    # the states are on the last pads of the row, in their order; the other pads are drawn and quiet
    slots = pg.evaluate(
        "[...document.querySelectorAll('#panel .mc.pad')].map(e => [e.dataset.slot, e.dataset.state, e.innerText.trim()])"
    )
    assert [s for s in slots if s[2]] == [["b6", "live", "as it is"], ["b7", "live", "hotter"], ["b8", "live", "drier"]]
    assert len(slots) == 8 and all(s[1] == "off" for s in slots[:5])
    # no Options anywhere: not on the Desk, not on the Song, not in History, and an old link lands on the Desk
    for tab in ("song", "desk"):
        pg.click(f"#tabs [data-t={tab}]")
        text = pg.inner_text("body")
        assert "Options" not in text and "Versions" not in text and "not rendered" not in text
    pg.click("#khist")
    assert "Options" not in pg.inner_text("#sheet")
    pg.click("#hclose")
    assert pg.locator("#topts, #sopts, #onow, #vgrid, [data-t=options]").count() == 0
    pg.goto(f"{rig.url}/app/#options")
    pg.wait_for_selector("#panel")
    assert pg.evaluate("location.hash") == "#desk" and pg.locator("#sheet.on").count() == 0
    assert rig.get("/api/options")[0] == 404 and rig.command("options.list")[0] == 404
    # the explanatory sentences the page had are gone, and the panel added none: its words are labels
    words = pg.evaluate(
        "[...document.querySelectorAll('#panel .mc.pad.cmp')].map(e => e.innerText.trim().split(/\\s+/).length)"
    )
    assert max(words) <= 3
    assert pg.errors == []
