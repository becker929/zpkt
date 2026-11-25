"""The Page renderer in /app/ (WebKit, on FakeLive): widgets by rule, the MiniLab map, greyed controls, and nothing
overflowing at 360, 390 and 1280 px. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import json

import pytest

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
    pg.wait_for_selector("#pcs .pc")
    pg.errors = errors  # type: ignore[attr-defined]
    return pg, reply


OVERFLOW = """() => {
  const out = [];
  document.querySelectorAll('#pcs .card, #pcs .pc, #pcs .pair, #minilab, #minilab .s, #hbot button, #pcs select').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width && (r.right > innerWidth + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.right));
  });
  const clipped = [...document.querySelectorAll('#pcs .pc > .l')].filter(l => l.scrollWidth > l.clientWidth + 1).map(l => l.textContent);
  const wide = [...document.querySelectorAll('#pcs .card')].filter(c => c.scrollWidth > c.clientWidth + 1).length;
  return {page: document.documentElement.scrollWidth - innerWidth, out, clipped, wide};
}"""


@pytest.mark.parametrize("width", [360, 390, 1280])
def test_the_biggest_page_overflows_nothing_at_this_width(browser, rig, width):
    pg, _ = open_page(browser, rig, width, big_spec())
    seen = set()
    for _ in range(4):  # a phone swipes through its pages of cards
        seen.update(pg.eval_on_selector_all("#pcs .card", "els => els.map(e => e.getAttribute('aria-label'))"))
        assert pg.evaluate(OVERFLOW) == {"page": 0, "out": [], "clipped": [], "wide": 0}
        nxt = pg.locator('[data-swipe="1"]')
        if not nxt.count() or nxt.is_disabled():
            break
        nxt.click()
    assert seen == {"Sub", "Knock", "Glue", "Bus"}
    assert pg.errors == []  # type: ignore[attr-defined]


def test_a_phone_swipes_cards_and_a_desktop_shows_them_all(browser, rig):
    phone, _ = open_page(browser, rig, 390, big_spec())
    assert phone.locator("#swipe").is_visible() and phone.locator("#pcs .card").count() == 2
    phone.click('[data-swipe="1"]')
    assert phone.eval_on_selector_all("#pcs .card", "els => els.map(e => e.getAttribute('aria-label'))") == [
        "Glue",
        "Bus",
    ]
    desk = browser.new_page(viewport={"width": 1280, "height": 900})
    desk.goto(rig.url + "/app/")
    desk.wait_for_selector("#pcs .card")
    assert desk.locator("#swipe").count() == 0 and desk.locator("#pcs .card").count() == 4


def test_widgets_follow_the_rules_and_the_minilab_map_is_the_assignment(browser, rig):
    pg, reply = open_page(browser, rig, 1280, big_spec())
    kinds = pg.eval_on_selector_all(
        "#pcs .pc", "els => els.map(e => e.className.split(' ').find(c => c.startsWith('w-')))"
    )
    assert {"w-fader", "w-knob", "w-key", "w-segmented", "w-list", "w-macro"} <= set(kinds)
    assert pg.locator("#pcs .pair").count() == 2  # an EQ band in each of the first two cards
    assert pg.locator("#pcs .pc .rg").count() >= 1  # the range stripe
    layout = rig.command("page.layout", {"id": reply["id"]})[1]["layout"]
    want = {s["slot"] for s in layout["minilab"][0]["slots"]}
    shown = set(pg.eval_on_selector_all("#minilab .s.on", "els => els.map(e => e.dataset.s)"))
    assert shown == want and want  # the screen shows what the hardware does


def test_touching_the_widgets_moves_live(browser, rig):
    spec = {"title": "Touch", "groups": [{"name": "g", "controls": [
        {"target": "Kick bus/volume"}, {"target": "Kick bus/mute"}, {"target": "Kick bus/desk Glue/Ratio"},
        {"target": "Kick bus/desk Glue/Attack"}]}]}  # fmt: skip
    pg, _ = open_page(browser, rig, 390, spec)
    song_track = rig.track("Kick bus")
    before = song_track.mixer_device.volume.value
    box = pg.locator('.pc[data-key="Kick bus/volume"] .w').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x, y - 40, steps=5)
    pg.mouse.up()
    pg.wait_for_function("window.zpkt.S.hear.changed >= 1")
    assert song_track.mixer_device.volume.value != before
    pg.click('.pc[data-key="Kick bus/mute"] button')
    pg.wait_for_function("window.zpkt.S.hear.changed >= 2")
    assert song_track.mute is True
    pg.click('.pc[data-key="Kick bus/desk Glue/Ratio"] .seg .key >> nth=2')
    pg.select_option('.pc[data-key="Kick bus/desk Glue/Attack"] select', "3")
    glue = next(d for d in song_track.devices if d.name == "desk Glue")
    param = {p.name: p for p in glue.parameters}
    pg.wait_for_function("window.zpkt.S.hear.changed >= 4")
    assert param["Ratio"].value == param["Ratio"].max and param["Attack"].value == 3
    assert pg.errors == []  # type: ignore[attr-defined]


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
    pg.wait_for_selector("#pcs .pc")
    pg.click('[aria-label="Ghosts"]')
    pg.wait_for_selector(".pc.missing")
    grey = pg.locator(".pc.missing")
    assert grey.count() == 1 and "Ghost" in grey.get_attribute("title")
    assert grey.get_attribute("aria-disabled") == "true"
    before = rig.desk.history.entries[:]
    box = grey.locator(".w").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] - 30, steps=4)
    pg.mouse.up()
    assert rig.desk.history.entries == before
