"""A hand on the desk in /app/ (WebKit, on FakeLive, at the walkthrough's 1200 x 800): the number follows the hand at
once and Live confirms or corrects it, one gesture is one undo step, the drag is relative with fine steps, the keyboard
and a typed value work, History shows values and checkpoints to go back to, the Hear bar says which song is open and
whether a meter sends, and unmapped slots are quiet. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import json
import re
import threading

import pytest

from tests.app.conftest import osc_spec, wait_for
from zpkt.app.bus import Command
from zpkt.live import meter

playwright_sync = pytest.importorskip("playwright.sync_api")

VOL, RATIO, GAIN = "Kick bus/volume", "Kick bus/desk Glue/Ratio", "Kick bus/desk EQ/1 Gain A"
SPEC = {"title": "Lead", "groups": [{"name": "g", "controls": [
    {"target": VOL, "label": "Level"}, {"target": GAIN, "label": "Tone"}, {"target": RATIO, "label": "Grit"},
    {"target": "Kick bus/mute", "label": "Space"}]}]}  # fmt: skip


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def open_lead(browser, rig, width=1200, height=800):
    code, reply = rig.desk.bus.submit(Command("page.make", "agent", {"spec": SPEC}))
    assert code == 200, reply
    pg = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_function("document.querySelector('#pagename')?.textContent === 'Lead'")
    pg.wait_for_selector("#panel .mc.live")
    pg.wait_for_function(f"window.zpkt.S.scales[{json.dumps(VOL)}]?.kind === 'continuous'")  # its scale has come
    pg.errors = errors  # type: ignore[attr-defined]
    return pg


def ctl(key: str) -> str:
    return f'#panel .mc[data-key="{key}"]'


def centre(pg, key):
    box = pg.locator(ctl(key) + " .w").bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def place(pg, key) -> float:
    return float(pg.locator(ctl(key)).get_attribute("data-n"))


def shown(pg, key) -> str:
    return pg.locator(ctl(key) + " .v").inner_text()


def drag(pg, key, dy, steps=8, release=True, pause=0):
    x, y = centre(pg, key)
    pg.mouse.move(x, y)
    pg.mouse.down()
    for i in range(1, steps + 1):
        pg.mouse.move(x, y + dy * i / steps)
        if pause:
            pg.wait_for_timeout(pause)
    if release:
        pg.mouse.up()


def settled(pg, key):
    pg.wait_for_function(f"!window.zpkt.own[{json.dumps(key)}]")


def live_text(rig, key) -> str:
    return next(v["s"] for v in rig.state()["values"].values() if v.get("key") == key)


# ---- finding 1: the value shows at once, Live confirms it, one gesture is one step -----------------------------------


def test_the_number_follows_the_hand_at_once_and_live_confirms_it(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    go, real = threading.Event(), rig.desk.write
    monkeypatch.setattr(rig.desk, "write", lambda pairs: (go.wait(10), real(pairs))[1])  # Live is slow
    was, before = shown(pg, VOL), len(rig.desk.history.entries)
    raw = rig.track("Kick bus").mixer_device.volume.value
    drag(pg, VOL, 60, release=False)  # down: quieter. The hand is still on it and Live has not answered.
    now = shown(pg, VOL)
    assert (
        now != was and now.endswith("dB") and float(now.split()[0]) < float(was.split()[0])
    )  # in the control's own units
    assert "sending" in pg.locator(ctl(VOL)).get_attribute("class").split()  # marked as on its way
    assert pg.locator("#chgpill").inner_text() == "1 changed"  # the counter too
    assert pg.locator("#bubble").inner_text() == now
    assert rig.track("Kick bus").mixer_device.volume.value == raw  # nothing has reached Live yet
    pg.mouse.up()
    assert shown(pg, VOL) == now and "sending" in pg.locator(ctl(VOL)).get_attribute("class").split()
    go.set()
    settled(pg, VOL)
    assert "sending" not in pg.locator(ctl(VOL)).get_attribute("class").split()
    assert shown(pg, VOL) == live_text(rig, VOL)  # Live's own text replaced the page's
    assert abs(float(shown(pg, VOL).split()[0]) - float(now.split()[0])) < 0.2  # and the page had read it right
    moves = [e for e in rig.desk.history.entries[before:] if e["k"] == "move"]
    assert len(moves) == 1  # the whole drag: one History row
    pg.click("#kundo")  # and one undo
    pg.wait_for_function(f"document.querySelector({json.dumps(ctl(VOL) + ' .v')}).textContent === {json.dumps(was)}")
    assert rig.track("Kick bus").mixer_device.volume.value == pytest.approx(raw)
    assert pg.locator("#chgpill").inner_text() == "0 changed"
    assert pg.errors == []  # type: ignore[attr-defined]


def test_a_value_live_settles_elsewhere_is_corrected_visibly(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    real = rig.desk.write
    monkeypatch.setattr(rig.desk, "write", lambda pairs: real([[k, 0.2] for k, _ in pairs]))  # Live lands elsewhere
    drag(pg, VOL, -60)
    mine = shown(pg, VOL)
    pg.wait_for_selector(ctl(VOL) + ".fixed")  # the number flashes: it was corrected
    assert shown(pg, VOL) == live_text(rig, VOL) != mine
    assert "sending" not in pg.locator(ctl(VOL)).get_attribute("class").split()
    assert place(pg, VOL) == pytest.approx(next(v["n"] for v in rig.state()["values"].values() if v.get("key") == VOL))


def test_a_refused_move_puts_the_control_back(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    was = shown(pg, VOL)

    def refuse(pairs):
        raise OSError("Live is gone")

    monkeypatch.setattr(rig.desk, "write", refuse)
    drag(pg, VOL, -60)
    settled(pg, VOL)
    assert shown(pg, VOL) == was and pg.locator("#chgpill").inner_text() == "0 changed"
    assert pg.locator("#toast").inner_text() != ""


# ---- finding 2: the drag is relative, with fine steps; the keyboard; typing ------------------------------------------


def test_the_drag_is_relative_200_px_for_the_range_and_shift_or_a_slow_hand_is_fine(browser, rig):
    pg = open_lead(browser, rig)
    box = pg.locator(ctl(VOL) + " .w").bounding_box()
    start = place(pg, VOL)
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] - 4)  # pressed at the bottom of the fader:
    pg.mouse.down()
    pg.mouse.up()
    assert place(pg, VOL) == start  # it does not jump to the pointer
    drag(pg, VOL, 100)  # 100 px less the 6 that decide the touch: just under half the range
    moved = start - place(pg, VOL)
    assert 0.42 < moved < 0.5, moved
    settled(pg, VOL)
    start = place(pg, VOL)
    pg.keyboard.down("Shift")
    drag(pg, VOL, -100)
    pg.keyboard.up("Shift")
    assert 0.07 < place(pg, VOL) - start < 0.11  # a fifth of that
    settled(pg, VOL)
    start = place(pg, VOL)
    drag(pg, VOL, -40, steps=40, pause=30)  # about 30 px a second: a slow hand
    assert 0.03 < place(pg, VOL) - start < 0.1
    assert (
        pg.evaluate(f"getComputedStyle(document.querySelector({json.dumps(ctl(VOL) + ' .w')})).touchAction") == "none"
    )


def test_a_click_focuses_and_the_keys_step_in_one_undo_step(browser, rig):
    pg = open_lead(browser, rig)
    sent: list[str] = []
    pg.on("request", lambda r: sent.append(r.post_data or "") if "mix.set" in (r.post_data or "") else None)
    before = len(rig.desk.history.entries)
    x, y = centre(pg, GAIN)
    pg.mouse.click(x, y)
    focused = "document.activeElement.closest('.mc')?.dataset.key"
    assert pg.evaluate(focused) == GAIN and sent == []  # a click gives it the keyboard and moves nothing
    start = place(pg, GAIN)
    pg.keyboard.press("ArrowUp")
    assert place(pg, GAIN) == pytest.approx(start + 0.01)
    assert shown(pg, GAIN) != "" and pg.locator("#chgpill").inner_text() == "1 changed"  # at once
    pg.keyboard.press("Shift+ArrowUp")
    assert place(pg, GAIN) == pytest.approx(start + 0.012)
    pg.keyboard.press("PageUp")
    assert place(pg, GAIN) == pytest.approx(start + 0.112)
    pg.keyboard.press("ArrowDown")
    assert place(pg, GAIN) == pytest.approx(start + 0.102)
    settled(pg, GAIN)
    assert pg.evaluate(focused) == GAIN  # the redraw that confirms it leaves the keyboard where it was
    pg.keyboard.press("ArrowUp")
    assert place(pg, GAIN) == pytest.approx(start + 0.112, abs=0.002)
    settled(pg, GAIN)
    assert len([e for e in rig.desk.history.entries[before:] if e["k"] == "move"]) == 1  # keys in a row: one step
    assert pg.errors == []  # type: ignore[attr-defined]


def test_enter_or_a_double_click_types_a_value_where_the_page_knows_the_scale(browser, rig):
    pg = open_lead(browser, rig)
    pg.locator(ctl(VOL) + " .w").focus()
    pg.keyboard.press("Enter")
    field = pg.locator(ctl(VOL) + " .vt")
    field.wait_for()
    assert field.bounding_box()["height"] >= 44
    field.fill("-6")
    pg.keyboard.press("Enter")
    settled(pg, VOL)
    assert pg.locator(".vt").count() == 0
    got = shown(pg, VOL)
    assert got.endswith("dB") and abs(float(got.split()[0]) + 6) < 0.3, got  # Live's own text, at about -6 dB
    x, y = centre(pg, GAIN)
    pg.mouse.dblclick(x, y)
    field = pg.locator(ctl(GAIN) + " .vt")
    field.wait_for()
    was = shown(pg, GAIN)
    field.fill("3 dB")
    pg.keyboard.press("Escape")  # Escape leaves it as it was
    assert pg.locator(".vt").count() == 0 and pg.evaluate(f"!window.zpkt.own[{json.dumps(GAIN)}]")
    assert shown(pg, GAIN) == was
    pg.mouse.dblclick(x, y)
    pg.locator(ctl(GAIN) + " .vt").fill("nonsense")
    pg.keyboard.press("Enter")
    assert "not a value" in pg.locator("#toast").inner_text()
    pg.locator(ctl(RATIO) + " .w").focus()  # a list of settings has no number to type
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(100)
    assert pg.locator(".vt").count() == 0
    assert pg.errors == []  # type: ignore[attr-defined]


def test_the_pages_reading_of_a_place_matches_lives_text(browser, rig):
    pg = open_lead(browser, rig)
    for n in (0.1, 0.37, 0.5, 0.81):  # between the stops the app handed over, the page reads off a straight line
        rig.command("mix.set", {"norms": [[GAIN, n]]})
        wait_for(
            lambda n=n: abs(next(v["n"] for v in rig.state()["values"].values() if v.get("key") == GAIN) - n) < 1e-6
        )
        mine = pg.evaluate(f"window.zpkt.textAt({json.dumps(GAIN)}, {n})")
        assert mine.split()[1:] == live_text(rig, GAIN).split()[1:]
        assert abs(float(mine.split()[0]) - float(live_text(rig, GAIN).split()[0])) <= 0.11, (
            mine,
            live_text(rig, GAIN),
        )
        back = pg.evaluate(f"window.zpkt.placeOf({json.dumps(GAIN)}, {json.dumps(mine)}, {json.dumps(mine)})")
        assert back == pytest.approx(n, abs=0.01)
    assert pg.evaluate("window.zpkt.textAt('No such/key', 0.25)") == "25%"  # no scale: the place itself


# ---- findings 3 and 4: History rows with values, undone rows, checkpoints to go back to -------------------------------


def test_history_rows_say_the_label_and_the_values_and_grey_what_is_undone(browser, rig):
    pg = open_lead(browser, rig)
    was = shown(pg, VOL)
    drag(pg, VOL, 40)
    settled(pg, VOL)
    now = shown(pg, VOL)
    pg.click("#khist")
    pg.wait_for_function("document.querySelector('#hrows .he:not(.cp)')?.textContent.includes('dB →')")
    row = pg.locator("#hrows .he:not(.cp)").first
    text = row.inner_text()
    assert "Level" in text and was in text and now in text and "→" in text  # the on-screen label, old → new, in dB
    assert "touch-" not in pg.locator("#sheet").inner_text()  # the gesture's id is not for reading
    pg.click("#hundo")
    pg.wait_for_selector("#hrows .he.undone")
    undone = pg.locator("#hrows .he.undone")
    assert "undone" in undone.inner_text() and "Level" in undone.inner_text()  # still listed, marked
    assert float(undone.locator(".ht").evaluate("e => getComputedStyle(e).opacity")) < 0.6
    pg.click("#hredo")
    pg.wait_for_function("!document.querySelector('#hrows .he.undone')")
    assert shown(pg, VOL) == now


def test_a_checkpoint_is_named_saved_at_once_and_can_be_gone_back_to(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    rig.command("history.checkpoint", {"name": "v171518"})  # names a machine made, as the walkthrough saw them
    rig.command("history.checkpoint", {"name": "start-20261125-1701"})
    go, real = threading.Event(), rig.desk.make_checkpoint
    monkeypatch.setattr(rig.desk, "make_checkpoint", lambda *a, **k: (go.wait(10), real(*a, **k))[1])
    was = shown(pg, VOL)
    pg.click("#khist")
    pg.wait_for_selector("#cpname")
    said = pg.locator("#sheet").inner_text()
    assert "v171518" not in said and "start-2026" not in said and "Start of session" in said  # never a bare id
    pg.fill("#cpname", "before the lead")
    pg.click("#hver")
    pg.wait_for_selector("#cpsaving")  # at once, though reading the mix out of Live takes seconds
    assert (
        "Saving" in pg.locator("#cpsaving").inner_text() and "before the lead" in pg.locator("#cpsaving").inner_text()
    )
    assert pg.locator("#hver").is_disabled() and "Saving" in pg.locator("#hver").inner_text()
    go.set()
    pg.wait_for_selector('#hrows .he.cp[data-cp="before the lead"]')
    assert pg.locator("#cpsaving").count() == 0 and pg.input_value("#cpname") == ""
    back = pg.locator('#hrows button[data-back="before the lead"]')
    assert back.inner_text().strip() == "Go back" and back.bounding_box()["height"] >= 44
    pg.click("#hclose")
    drag(pg, VOL, 50)
    settled(pg, VOL)
    moved = shown(pg, VOL)
    assert moved != was
    pg.click("#khist")
    pg.click('#hrows button[data-back="before the lead"]')
    pg.wait_for_function(f"document.querySelector({json.dumps(ctl(VOL) + ' .v')}).textContent === {json.dumps(was)}")
    assert "Went back to “before the lead”" in pg.locator("#hrows .he:not(.cp)").first.inner_text()
    pg.click("#hundo")  # going back is a step like any other
    pg.wait_for_function(f"document.querySelector({json.dumps(ctl(VOL) + ' .v')}).textContent === {json.dumps(moved)}")
    pg.click("#hver")  # no name typed: the date and time, shown as one
    pg.wait_for_function("document.querySelectorAll('#hrows .he.cp:not(.saving)').length >= 4")
    label = pg.locator("#hrows .he.cp .ht").first.inner_text()
    assert re.fullmatch(r"\d{1,2} [A-Z][a-z]{2}, \d\d:\d\d", label), label  # "25 Nov, 17:15"
    assert pg.errors == []  # type: ignore[attr-defined]


# ---- findings 5 and 7: which song is open; the spectrum and the level say when there is nothing to show ----------------


def test_the_hear_bar_names_the_set_its_tempo_and_the_bar(browser, rig):
    pg = open_lead(browser, rig)
    song = rig.state()["song"]
    assert pg.locator("#setname").inner_text() == song["name"]
    assert pg.locator("#songfacts").inner_text() == "160 BPM · 4/4"
    bars = song["bars"]
    assert pg.locator("#barno").inner_text() == (f"bar 1 of {bars}" if bars else "bar 1")
    rig.send({"t": "pos", "b": 20.0, "p": False, "bpm": 127.5})
    pg.wait_for_function("document.querySelector('#songfacts').textContent.startsWith('127.5 BPM')")
    assert pg.locator("#barno").inner_text().startswith("bar 6")
    rig.send({"t": "loop", "loop": "drop"})  # a loop is why the bar jumps back: it is said
    pg.wait_for_selector("#looppill")
    assert pg.locator("#looppill").inner_text() == "loop: drop"
    phone = browser.new_page(viewport={"width": 375, "height": 800})
    phone.goto(rig.url + "/app/")
    phone.wait_for_selector("#setname")
    assert phone.evaluate("document.documentElement.scrollWidth - innerWidth") == 0


def test_no_meter_is_said_and_the_level_reads_listens_peak(browser, rig):
    pg = open_lead(browser, rig)
    none = pg.locator("#spec.none")
    assert none.inner_text() == "No spectrum · desk meter not on Main"
    assert "desk meter device is not on Main" in none.get_attribute("aria-label")
    level = pg.locator("#lvl")
    assert level.get_attribute("data-state") == "off" and pg.locator("#lvl .ln").inner_text() == "Listen off"
    rig.meter.send(osc_spec([0.1] * len(meter.centers())))
    pg.wait_for_selector("#spec:not(.none) i")  # the meter sends: bars
    tell = "window.dispatchEvent(new CustomEvent('zpkt-listen', {detail: %s}))"  # what listen.js sends
    pg.evaluate(tell % json.dumps({"state": "on", "peak": 0.5}))
    assert level.get_attribute("data-state") == "on" and pg.locator("#lvl .ln").inner_text() == "-6.0 dB"
    width = pg.evaluate("parseFloat(document.querySelector('#lvl .lb i').style.width)")
    assert 85 < width < 95  # -6 dB on a 60 dB scale
    rig.send({"t": "pos", "b": 4.0, "p": True})  # the bar is redrawn: the level stays
    pg.wait_for_function("document.querySelector('#barno').textContent.startsWith('bar 2')")
    assert (
        pg.locator("#lvl .ln").inner_text() == "-6.0 dB" and pg.locator("#lvl").get_attribute("aria-valuenow") == "-6"
    )
    pg.evaluate(tell % json.dumps({"state": "on", "peak": 0}))
    assert pg.locator("#lvl .ln").inner_text() == "silent"
    pg.evaluate(tell % json.dumps({"state": "off", "peak": 0}))
    assert level.get_attribute("data-state") == "off" and pg.locator("#lvl .ln").inner_text() == "Listen off"
    pg.evaluate("window.zpkt.S.meterAt = Date.now() - 60000")  # the device left Main: its last bars do not stay
    pg.wait_for_selector("#spec.none")


# ---- findings 8, 9 and 10 --------------------------------------------------------------------------------------------


def test_a_new_pages_button_is_in_view_in_the_page_list(browser, rig):
    pg = open_lead(browser, rig)  # the made page is the last of the list, in a window 800 px high
    on = pg.locator("#side .pl .key.on")
    assert on.inner_text() == "Lead"
    box, side = on.bounding_box(), pg.locator("#side").bounding_box()
    assert box["y"] >= side["y"] and box["y"] + box["height"] <= min(800, side["y"] + side["height"]) + 0.5
    pg.click('#side button[data-page="0"]')
    pg.wait_for_function("window.zpkt.S.state.page === 0 && !window.zpkt.S.pend")
    first = pg.locator("#side .pl .key.on").bounding_box()
    assert first["y"] >= side["y"]


def test_no_minilab_is_not_an_error(browser, rig):
    pg = open_lead(browser, rig)
    assert pg.locator("#mlchip").inner_text() == "on MiniLab"
    rig.desk.set_state(None, "no MiniLab 3 in Live")
    pg.wait_for_function("document.querySelector('#mlchip')?.textContent === 'no MiniLab'")
    assert "quiet" in pg.locator("#mlchip").get_attribute("class") and "acc" not in pg.locator("#mlchip").get_attribute(
        "class"
    )
    assert "on" not in (pg.locator("#lock").get_attribute("class") or "").split()  # no red line across the page
    assert pg.locator("#livepill").inner_text() == "Live" and "warn" not in pg.locator("#livepill").get_attribute(
        "class"
    )
    rig.desk.set_state(None, "Live does not answer (gone)")  # that one is an error, and looks it
    pg.wait_for_selector("#lock.on")


def test_unmapped_slots_are_quiet(browser, rig):
    pg = open_lead(browser, rig)
    off = pg.locator("#panel .mc.off")
    assert off.count() == 16
    assert pg.eval_on_selector_all("#panel .mc.off", "els => els.map(e => e.innerText.trim()).filter(Boolean)") == []
    assert all(
        o <= 0.25
        for o in pg.eval_on_selector_all("#panel .mc.off", "els => els.map(e => +getComputedStyle(e).opacity)")
    )
    k8 = pg.locator('#panel .mc[data-slot="k8"]')
    assert (
        k8.locator(".w").get_attribute("aria-label") == "Knob 8: not mapped"
        and k8.get_attribute("title") == "Knob 8: not mapped"
    )
    box, live = k8.bounding_box(), pg.locator('#panel .mc[data-slot="k1"]').bounding_box()
    assert abs(box["width"] - live["width"]) < 2  # still in its place on the map
