"""The Page renderer in /app/ (WebKit, on FakeLive): every page of controls is one panel, a map of the MiniLab 3 with
all 20 slots in their places. Mapped slots are live, the rest are greyed, and nothing overflows at 360, 375, 390 and
1280 px. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import json

import pytest

from tests.app.conftest import wait_for
from zpkt.app.bus import Command

playwright_sync = pytest.importorskip("playwright.sync_api")

EQ = "Kick bus/desk EQ/"


def big_spec() -> dict:
    """24 controls in 4 cards of 6: every widget the rules make (fader, knob, key, segmented, list, pair, macro)."""
    band = lambda n: [  # noqa: E731
        {"target": f"{EQ}{n} Gain A", "role": "level", "weight": 3, "range": ["-6 dB", "6 dB"]},
        {"target": f"{EQ}{n} Frequency A", "role": "tone"},
        {"target": f"{EQ}{n} Q A", "role": "amount", "weight": 1},
        {"target": f"{EQ}{n} Filter On A"},
        {"target": f"{EQ}{n} Filter Type A"},
        {"target": f"{EQ}{n} Q B", "role": "amount", "label": "Q two"},
    ]
    return {
        "title": "Everything at once",
        "groups": [
            {"name": "Sub", "controls": band(1)},
            {"name": "Knock", "controls": band(2)},
            {
                "name": "Glue",
                "controls": [
                    {"target": "Kick bus/desk Glue/Threshold"},
                    {"target": "Kick bus/desk Glue/Dry/Wet"},
                    {"target": "Kick bus/desk Glue/Ratio"},
                    {"target": "Kick bus/desk Sat/Post Clip Mode"},
                    {"target": "Kick bus/desk Glue/Attack"},
                    {
                        "label": "Darker",
                        "macro": [
                            {"target": f"{EQ}3 Gain A", "low": "0 dB", "high": -6},
                            {"target": "Kick bus/volume", "low": "min", "high": "max"},
                        ],
                    },
                ],
            },
            {
                "name": "Bus",
                "controls": [
                    {"target": "Kick bus/volume"},
                    {"target": "Kick bus/pan"},
                    {"target": "Kick bus/mute"},
                    {"target": "Kick bus/solo"},
                    {"target": "Kick bus/send Space"},
                    {"target": "Kick bus/send Echo"},
                ],
            },
        ],
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


def open_page(browser, rig, width, spec, page_index=None):
    code, reply = rig.desk.bus.submit(Command("page.make", "agent", {"spec": spec}))
    assert code == 200, reply
    pg = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#panel .mc.live")
    pg.wait_for_function(f"document.querySelector('#pagename').textContent === {json.dumps(spec['title'])}")
    pg.errors = errors  # type: ignore[attr-defined]
    return pg, reply


THREE = {"title": "Three", "groups": [{"name": "g", "controls": [
    {"target": "Kick bus/volume"}, {"target": "Kick bus/pan"}, {"target": "Kick bus/mute"}]}]}  # fmt: skip

OVERFLOW = """() => {
  const out = [];
  document.querySelectorAll('#panel, #panel .mc, #panel .w, #mlpages button, #hbot button').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width && (r.right > innerWidth + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.right));
  });
  const clipped = [...document.querySelectorAll('#panel .mc.live > .l')].filter(l => l.scrollHeight > l.clientHeight + 1).map(l => l.textContent);
  const small = [...document.querySelectorAll('#panel .mc .w')].map(w => w.getBoundingClientRect())
    .filter(r => r.width < 44 || r.height < 44).length;
  return {page: document.documentElement.scrollWidth - innerWidth, out, clipped, small,
          slots: document.querySelectorAll('#panel .mc').length};
}"""

# Where the blocks sit: [knob 1, knob 4, knob 5, fader 1, pad 1, pad 4, pad 5, pad 8] as {x, y} of their centres.
PLACES = """() => ['k1','k4','k5','f1','b1','b4','b5','b8'].map(s => {
  const r = document.querySelector(`#panel .mc[data-slot="${s}"]`).getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })"""


def drag(pg, selector, dx, dy):
    box = pg.locator(selector).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx, y + dy, steps=5)
    pg.mouse.up()


def on_page(pg, n):
    pg.wait_for_function(f"window.zpkt.S.state.page === {n} && !window.zpkt.S.pend")


@pytest.mark.parametrize("width", [360, 375, 390, 1280])
def test_the_biggest_page_overflows_nothing_at_this_width(browser, rig, width):
    pg, reply = open_page(browser, rig, width, big_spec())
    layout = rig.command("page.layout", {"id": reply["id"]})[1]["layout"]
    assert len(layout["panels"]) >= 2
    seen = set()
    buttons = pg.locator("#mlpages button")
    assert buttons.count() == len(layout["panels"])
    for k in range(buttons.count()):
        if k:
            buttons.nth(k).click()
            on_page(pg, int(buttons.nth(k).get_attribute("data-page")))
        seen.update(pg.eval_on_selector_all("#panel .mc .g", "els => els.map(e => e.textContent).filter(Boolean)"))
        assert pg.evaluate(OVERFLOW) == {"page": 0, "out": [], "clipped": [], "small": 0, "slots": 20}
    assert seen == {"Sub", "Knock", "Glue", "Bus"}  # the group is a small caption on its controls
    assert pg.errors == []  # type: ignore[attr-defined]


def test_three_mapped_controls_are_twenty_slots_with_seventeen_greyed(browser, rig):
    pg, _ = open_page(browser, rig, 375, THREE)
    assert pg.locator("#panel .mc").count() == 20
    assert pg.locator("#panel .mc.live").count() == 3 and pg.locator("#panel .mc.off").count() == 17
    live = pg.eval_on_selector_all("#panel .mc.live", "els => els.map(e => e.dataset.slot).sort()")
    assert live == ["b1", "f1", "k1"]
    assert pg.locator("#mlpages").count() == 0  # one MiniLab page: no numbered buttons
    # a greyed slot is in its place, says what it is to a screen reader, and is not a control
    k6 = pg.locator('#panel .mc[data-slot="k6"]')
    assert k6.get_attribute("aria-disabled") == "true"
    assert k6.locator(".w").get_attribute("aria-label") == "Knob 6: not mapped"
    assert pg.locator('#panel .mc[data-slot="f2"] .w').get_attribute("aria-label") == "Fader 2: not mapped"
    assert pg.locator('#panel .mc[data-slot="b3"] .w').get_attribute("aria-label") == "Pad 3: not mapped"
    assert pg.locator("#panel .mc.off [role=slider], #panel .mc.off button").count() == 0
    assert float(k6.evaluate("e => getComputedStyle(e).opacity")) < 0.6
    track = rig.track("Kick bus")
    sent: list[str] = []
    pg.on("request", lambda r: sent.append(r.post_data or "") if r.url.endswith("/api/command") else None)
    before, entries = track.mixer_device.panning.value, len(rig.desk.history.entries)
    drag(pg, '#panel .mc[data-slot="k6"] .w', 0, -40)  # a greyed knob: nothing is sent
    drag(pg, '#panel .mc[data-slot="f3"] .w', 0, -40)
    pg.locator('#panel .mc[data-slot="b5"] .w').click()
    pg.wait_for_timeout(150)
    assert sent == [] and len(rig.desk.history.entries) == entries
    drag(pg, '#panel .mc[data-slot="k1"] .w', 0, -40)  # the mapped knob: mix.set
    pg.wait_for_function("window.zpkt.S.hear.changed >= 1")
    assert sent and all(json.loads(b)["kind"] == "mix.set" for b in sent)
    assert json.loads(sent[-1])["args"]["norms"][0][0] == "Kick bus/pan"
    assert track.mixer_device.panning.value > before
    assert pg.errors == []  # type: ignore[attr-defined]


def test_the_panel_sits_like_the_minilab_and_folds_on_a_phone(browser, rig):
    pg, reply = open_page(browser, rig, 1280, THREE)
    k1, k4, k5, f1, b1, b4, b5, b8 = pg.evaluate(PLACES)
    assert k1["x"] < k4["x"] < f1["x"] and abs(k1["y"] - k4["y"]) < 2  # knobs 1-4 in a row, the faders to their right
    assert k5["y"] > k1["y"] + 40 and abs(k5["x"] - k1["x"]) < 2  # knobs 5-8 under them
    assert (
        b1["y"] > k5["y"] + 40 and abs(b1["y"] - b8["y"]) < 2 and b1["x"] < b4["x"] < b5["x"] < b8["x"]
    )  # one row of 8
    layout = rig.command("page.layout", {"id": reply["id"]})[1]["layout"]
    want = {s["slot"] for s in layout["minilab"][0]["slots"]}
    shown = set(pg.eval_on_selector_all("#panel .mc.live", "els => els.map(e => e.dataset.slot)"))
    assert shown == want and want  # the screen shows what the hardware does
    phone = browser.new_page(viewport={"width": 375, "height": 900})
    phone.goto(rig.url + "/app/")
    phone.wait_for_selector("#panel .mc.live")
    k1, k4, k5, f1, b1, b4, b5, b8 = phone.evaluate(PLACES)
    # folded: knobs, pads 1-4, faders, pads 5-8, each block the full width
    assert k1["y"] < k5["y"] < b1["y"] < f1["y"] < b5["y"]
    assert abs(b1["x"] - b5["x"]) < 2 and abs(b4["x"] - b8["x"]) < 2 and abs(k1["x"] - f1["x"]) < 2


def test_touching_the_widgets_moves_live(browser, rig):
    spec = {"title": "Touch", "groups": [{"name": "g", "controls": [
        {"target": "Kick bus/volume"}, {"target": "Kick bus/mute"}, {"target": "Kick bus/desk Glue/Ratio"},
        {"target": "Kick bus/desk Glue/Attack"}]}]}  # fmt: skip
    pg, _ = open_page(browser, rig, 390, spec)
    song_track = rig.track("Kick bus")
    before = song_track.mixer_device.volume.value
    drag(pg, '.mc.fader[data-key="Kick bus/volume"] .w', 0, -40)
    pg.wait_for_function("window.zpkt.S.hear.changed >= 1")
    assert song_track.mixer_device.volume.value != before
    pad = pg.locator('.mc.pad[data-key="Kick bus/mute"] button')
    assert pad.get_attribute("aria-pressed") == "false"
    pad.click()
    pg.wait_for_function("window.zpkt.S.hear.changed >= 2")
    assert song_track.mute is True
    pg.wait_for_selector('.mc.pad.on[data-key="Kick bus/mute"] button[aria-pressed="true"]')
    glue = next(d for d in song_track.devices if d.name == "desk Glue")
    param = {p.name: p for p in glue.parameters}
    ratio = pg.locator('.mc.knob[data-key="Kick bus/desk Glue/Ratio"]')
    assert int(ratio.get_attribute("data-steps")) >= 2  # a choice is a knob with stops
    drag(pg, '.mc.knob[data-key="Kick bus/desk Glue/Ratio"] .w', 0, -200)
    pg.wait_for_function("window.zpkt.S.hear.changed >= 3")
    # the drag passes the middle stop on its way: the last place sent is the one that stays
    assert wait_for(lambda: param["Ratio"].value == param["Ratio"].max)
    pg.wait_for_function("!window.zpkt.own['Kick bus/desk Glue/Ratio']")
    attack = pg.locator('.mc.knob[data-key="Kick bus/desk Glue/Attack"] .w')  # the keyboard: one stop up
    was = param["Attack"].value
    attack.focus()
    pg.keyboard.press("ArrowUp")
    pg.wait_for_function("window.zpkt.S.hear.changed >= 4")
    assert param["Attack"].value == was + 1
    assert pg.errors == []  # type: ignore[attr-defined]


def test_the_range_and_the_macro_are_drawn_in_their_slots(browser, rig):
    pg, _ = open_page(browser, rig, 1280, big_spec())
    assert pg.locator("#panel .mc .rg").count() >= 1  # the stretch worth playing
    pg.click("#mlpages button >> nth=1")
    pg.wait_for_selector("#panel .mc.macro")
    macro = pg.locator("#panel .mc.macro")
    assert macro.count() == 1 and macro.locator(".l").inner_text() == "Darker"
    assert macro.locator("[role=slider]").count() == 0  # a macro is turned on the MiniLab


def test_a_page_of_two_minilab_pages_has_numbered_buttons_and_a_phone_swipes(browser, rig):
    pg, _ = open_page(browser, rig, 390, big_spec())
    first = pg.evaluate("window.zpkt.S.state.page")
    nums = pg.locator("#mlpages button")
    assert nums.count() >= 2 and nums.nth(0).inner_text() == "1" and "on" in nums.nth(0).get_attribute("class")
    two = int(nums.nth(1).get_attribute("data-page"))
    drag(pg, '#panel .mc[data-slot="k1"] .w', -140, 4)  # swipe left on a live knob: the next MiniLab page, no move
    on_page(pg, two)
    assert pg.evaluate("window.zpkt.S.hear.changed") == 0
    assert "on" in pg.locator("#mlpages button").nth(1).get_attribute("class")
    assert pg.locator("#pagename").inner_text() == "Everything at once"
    drag(pg, "#panel .mp1", 140, 0)  # swipe right: back
    on_page(pg, first)
    drag(pg, "#panel .mp1", 140, 0)  # no page before the first: nothing happens
    pg.wait_for_timeout(150)
    assert pg.evaluate("window.zpkt.S.state.page") == first and pg.evaluate("window.zpkt.S.pend") is None
    wide = browser.new_page(viewport={"width": 1280, "height": 900})
    wide.goto(rig.url + "/app/")
    wide.wait_for_selector("#mlpages button")
    drag(wide, '#panel .mc[data-slot="k1"] .w', -140, 0)  # a desktop does not swipe
    wide.wait_for_timeout(150)
    assert wide.evaluate("window.zpkt.S.state.page") == first


def test_the_desks_own_pages_are_the_same_panel(browser, rig):
    pg = browser.new_page(viewport={"width": 375, "height": 900})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#panel .mc.live")
    desk = rig.get("/api/desk")[1]
    every = {f"k{i}" for i in range(1, 9)} | {f"f{i}" for i in range(1, 5)} | {f"b{i}" for i in range(1, 9)}
    greyed = 0
    for n in (0, 1):
        if n:
            pg.evaluate(f"window.zpkt.armPage({n})")
            on_page(pg, n)
        mapped = set(desk["pages"][n]["controls"])
        assert pg.locator("#panel .mc").count() == 20
        off = set(pg.eval_on_selector_all("#panel .mc.off", "els => els.map(e => e.dataset.slot)"))
        assert off == every - mapped
        greyed += len(off)
        fit = pg.evaluate(OVERFLOW)  # the desk's long names ("Chord and splash bus volume") are cut after two lines
        assert {**fit, "clipped": []} == {"page": 0, "out": [], "clipped": [], "small": 0, "slots": 20}
    assert greyed > 0  # a desk page that leaves slots free shows them greyed
    assert pg.locator("#pcs, .legacy, .card").count() == 0  # one renderer, one look
    assert errors == []


def test_a_missing_target_is_a_greyed_control_that_does_not_move(browser, rig):
    folder = rig.tmp / "sets" / "pages" / "HW002_121_pp_finish"
    folder.mkdir(parents=True)
    (folder / "ghosts.json").write_text(json.dumps({"schema": 2, "title": "Ghosts", "groups": [{"name": "g", "controls": [
        {"target": "Ghost/volume"}, {"target": "Kick bus/volume"}]}]}))  # fmt: skip
    rig.desk.bus.submit(Command("page.make", "agent", {"spec": big_spec()}))
    # a page whose file the set no longer fits: a made surface names it, the page file is the old one
    surf = rig.tmp / "surfaces" / "ghosts.json"
    surf.parent.mkdir(exist_ok=True)
    surf.write_text(json.dumps({"name": "Ghosts", "controls": {"f1": {"track": "Kick bus", "param": "volume"}},
                                "page_id": "ghosts", "hardware": 0}))  # fmt: skip
    rig.desk.restart_pager()
    pg = browser.new_page(viewport={"width": 390, "height": 900})
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#panel .mc.live")
    pg.click('[aria-label="Ghosts"]')
    pg.wait_for_selector(".mc.missing")
    grey = pg.locator(".mc.missing")
    assert grey.count() == 1 and "Ghost" in grey.get_attribute("title")
    assert grey.get_attribute("aria-disabled") == "true"
    assert grey.locator(".v").inner_text() == "not in this set"  # not the same words as an unmapped slot
    assert pg.locator("#panel .mc").count() == 20 and pg.locator("#panel .mc.off").count() == 18
    before = rig.desk.history.entries[:]
    drag(pg, ".mc.missing .w", 0, -30)
    assert rig.desk.history.entries == before
