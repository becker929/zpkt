"""The second cold walkthrough's findings on /app/ (WebKit, on FakeLive, at her 1200 x 800 and on a phone): solo and
mute are on the Hear bar and clear with one tap; one undo takes a control back to where it was; every History row is
a place to go back to; a build is not offered on another set; the spectrum turns itself on; "N changed" names its
checkpoint; History is docked on a desktop and a sheet that swallows no touch on a phone; a knob moves from the first
pixel in round units and its number is typed where it stands; a link to a Page shows it loading; the Song has a bar
ruler; controls are not made anew on every event. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import json
import threading
import time

import pytest

from tests.app.conftest import osc_spec, wait_for
from tests.app.test_desk_touch import GAIN, RATIO, VOL, centre, ctl, drag, open_lead, place, settled, shown
from tests.app.test_song import MIX_SET, quick_live, song_rig  # noqa: F401  (fixtures)
from zpkt.app import jobs
from zpkt.app.bus import Command
from zpkt.live import meter

playwright_sync = pytest.importorskip("playwright.sync_api")

FREQ = "Kick bus/desk EQ/1 Frequency A"


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def flag(rig, track: str, name: str, on: bool) -> None:
    """Solo or mute a track in Live itself, as a hand on Live would."""
    rig.conn.run(f"next(t for t in song.tracks if t.name == {track!r}).{name} = {on!r}\nresult = 1")


def slow_writes(rig, monkeypatch) -> threading.Event:
    """Live takes its time over every write until the event is set."""
    go, real = threading.Event(), rig.desk.write
    monkeypatch.setattr(rig.desk, "write", lambda pairs: (go.wait(10), real(pairs))[1])
    return go


def rows(pg) -> list[str]:
    return pg.locator("#hrows > .he").all_inner_texts()


# ---- 1: solo and mute --------------------------------------------------------------------------------------------------


def test_a_soloed_track_is_lit_by_the_transport_and_one_tap_clears_it(browser, rig):
    flag(rig, "Kick bus", "solo", True)  # soloed before the page opens: the walkthrough's kick bus
    pg = open_lead(browser, rig)
    chip = pg.locator("#flags .chip.solo")
    assert chip.count() == 1 and "Kick bus" in chip.inner_text()
    assert chip.bounding_box()["height"] >= 44
    play, box = pg.locator("#kplay").bounding_box(), chip.bounding_box()
    assert abs(box["y"] - play["y"]) < 120  # by the transport, not somewhere up the page
    before = len(rig.desk.history.entries)
    chip.click()
    pg.wait_for_function("!document.querySelector('#flags .chip.solo')")
    assert rig.track("Kick bus").solo is False
    entry = rig.desk.history.entries[-1]  # a normal move: a History row, by you, that undo takes back
    assert len(rig.desk.history.entries) == before + 1 and entry["who"] == "you"
    assert entry["moves"][0]["key"] == "Kick bus/solo" and entry["moves"][0]["label"] == "Kick bus solo"
    assert "Kick bus solo" in pg.locator("#hrows .he.row").first.inner_text()
    pg.click("#kundo")
    pg.wait_for_selector("#flags .chip.solo")
    assert rig.track("Kick bus").solo is True
    flag(rig, "Hats bus", "solo", True)  # soloed in Live while the page is open: it shows without a reload
    pg.wait_for_function("document.querySelectorAll('#flags .chip.solo').length === 2")
    assert pg.errors == []  # type: ignore[attr-defined]


def test_many_muted_tracks_are_a_count_that_opens_the_list(browser, rig):
    names = [t.name for t in rig.live.song.tracks if not t.name.startswith("mon ")][:3]
    for name in names:
        flag(rig, name, "mute", True)
    pg = open_lead(browser, rig, width=390)
    count = pg.locator("#flags [data-flags=mute]")
    assert count.locator("span").inner_text() == "3" and pg.locator("#flagpop").is_hidden()
    assert pg.locator("#flags .chip.solo").count() == 0  # nothing is soloed: no solo mark at all
    count.click()
    assert pg.locator("#flagpop .chip.mute").count() == 3
    pg.locator(f'#flagpop .chip.mute[data-track="{names[0]}"]').click()
    pg.wait_for_function("document.querySelectorAll('#flags .chip.mute[data-track]').length === 2")  # two names: chips
    assert rig.track(names[0]).mute is False and pg.locator("#flagpop").is_hidden()
    assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") == 0


def test_the_monitors_own_tracks_and_switches_are_not_reported_as_a_solo(rig):
    rig.conn.run("m = __import__('sys').modules\nresult = 1")
    snap = rig.desk.call("m.DESK.snapshot()")
    assert not any(n.startswith("mon ") for n in snap["flags"]["tracks"]) and snap["flags"]["solo"] == []
    assert rig.state()["solo"] == [] and "Kick bus/solo" in rig.desk.history.cur  # known from inside Live, no ask


# ---- 2: one undo, return points, what Undo will do ----------------------------------------------------------------------


def test_a_drag_then_nudges_is_one_undo_and_the_button_says_where_it_goes(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    assert pg.locator("#kundo").is_disabled() and pg.locator("#kredo").is_disabled()  # nothing to take back or redo
    was, before = shown(pg, GAIN), len(rig.desk.history.entries)
    drag(pg, GAIN, -20)
    settled(pg, GAIN)
    pg.locator(ctl(GAIN) + " .w").focus()
    for key in ("ArrowDown", "Shift+ArrowDown", "Shift+ArrowDown"):
        pg.keyboard.press(key)
        pg.wait_for_timeout(120)
    settled(pg, GAIN)
    assert len([e for e in rig.desk.history.entries[before:] if e["k"] == "move"]) == 1
    said = pg.locator("#undowhat").inner_text()
    assert "Tone" in said and was in said  # the control, and the value Undo returns it to
    assert was in pg.locator("#kundo").get_attribute("aria-label")
    go = slow_writes(rig, monkeypatch)
    pg.click("#kundo")
    pg.wait_for_function(
        f"document.querySelector({json.dumps(ctl(GAIN) + ' .v')}).textContent === {json.dumps(was)}", timeout=1000
    )
    assert "sending" in pg.locator(ctl(GAIN)).get_attribute("class").split()  # shown before Live has answered
    go.set()
    settled(pg, GAIN)
    assert shown(pg, GAIN) == was
    pg.wait_for_function("document.querySelector('#kundo').disabled && !document.querySelector('#kredo').disabled")
    assert pg.errors == []  # type: ignore[attr-defined]


def test_a_history_row_is_a_place_to_go_back_to(browser, rig, monkeypatch):
    pg = open_lead(browser, rig)
    gain0, vol0 = shown(pg, GAIN), shown(pg, VOL)
    for key in (GAIN, VOL, GAIN):
        pg.locator(ctl(key) + " .w").focus()
        pg.keyboard.press("ArrowUp")
        settled(pg, key)
    pg.wait_for_function("document.querySelectorAll('#hrows .he.row').length === 3")
    assert pg.locator("#hrows [data-before]").count() == 0  # the way back shows on the row that is tapped
    oldest = pg.locator("#hrows .he.row").last
    oldest.click()
    back = pg.locator("#hrows [data-before]")
    assert back.count() == 1 and "Tone" in back.get_attribute("aria-label")
    go = slow_writes(rig, monkeypatch)
    back.click()
    want = f"document.querySelector({json.dumps(ctl(GAIN) + ' .v')}).textContent === {json.dumps(gain0)}"
    pg.wait_for_function(want, timeout=1000)  # at once, before Live has been written
    go.set()
    settled(pg, GAIN)
    settled(pg, VOL)
    assert (shown(pg, GAIN), shown(pg, VOL)) == (gain0, vol0)  # that step and the two after it, in one move
    assert "Back before Tone" in pg.locator("#hrows .he").first.inner_text()
    pg.click("#kundo")  # and the move is undoable
    pg.wait_for_function(f"document.querySelector({json.dumps(ctl(VOL) + ' .v')}).textContent !== {json.dumps(vol0)}")
    assert shown(pg, GAIN) != gain0
    assert pg.errors == []  # type: ignore[attr-defined]


def test_history_back_is_one_undoable_step_and_refuses_a_step_that_is_gone(rig):
    values = rig.state()["values"]
    a, b = [v["key"] for v in values.values() if v.get("key") and v.get("n") is not None and not v.get("q")][:2]
    start = {k: rig.desk.history.cur[k][1] for k in (a, b)}
    rig.command("mix.set", {"norms": [[a, 0.31]]})
    first = rig.desk.history.entries[-1]["id"]
    rig.command("mix.set", {"norms": [[b, 0.42]]})
    rig.command("mix.set", {"norms": [[a, 0.55]]})
    n = len(rig.desk.history.entries)
    code, reply = rig.command("history.back", {"entry": first})
    assert code == 200 and reply["moved"] == 2
    assert {k: rig.desk.history.cur[k][1] for k in (a, b)} == start
    entry = rig.desk.history.entries[-1]
    assert len(rig.desk.history.entries) == n + 1 and entry["k"] == "revert" and entry["before"]["id"] == first
    assert rig.command("history.undo")[0] == 200
    assert rig.desk.history.cur[a][1] != start[a] and rig.desk.history.cur[b][1] != start[b]
    assert rig.command("history.undo")[0] == 200  # the last change of a is undone...
    assert (
        rig.command("history.back", {"entry": rig.desk.history.entries[n - 1]["id"]})[0] == 409
    )  # ...so it is no return point
    assert rig.command("history.back", {"entry": 10**6})[0] == 409
    assert rig.desk.bus.submit(Command("history.back", "agent", {"entry": first}))[0] == 403


# ---- 3: a build names the set that is open ------------------------------------------------------------------------------


def open_in_live(rig, name: str) -> None:
    rig.live.song.file_path = f"/Sets/{name} Project/{name}.als" if name else ""
    rig.desk.bus.guard.forget()
    rig.desk.restart_pager()  # as the supervisor does once another set is in front


def test_the_build_is_not_offered_on_another_set_and_the_mix_set_opens_from_the_page(browser, song_rig, monkeypatch):  # noqa: F811
    rig = song_rig.rig
    open_in_live(rig, "HW002_121_pp_finish")
    opened: list[tuple[str, bool]] = []

    def fake_open(client, name, *, save_current=True, timeout_s=120.0):
        opened.append((name, save_current))
        rig.live.song.file_path = f"/Sets/{name} Project/{name}.als"
        return 1.5

    monkeypatch.setattr(jobs.session, "open_set", fake_open)
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#buildsets")
    assert pg.locator("#songbuild").count() == 0  # not offered: Live has another set in front
    assert (
        "HW002_121_pp_finish" in pg.locator("#setopen").inner_text() and MIX_SET in pg.locator("#setneed").inner_text()
    )
    pg.click("#openmix")
    pg.wait_for_selector("#sheet.on #openswap")
    said = pg.locator("#openswap").inner_text()
    assert "SAVED FIRST" in said.upper() and "HW002_121_pp_finish" in said and MIX_SET in said  # the consequence
    assert opened == []  # nothing before the press
    pg.click("#opengo")
    pg.wait_for_selector("#songbuild")  # the build is offered now, for the set it names
    assert opened == [(MIX_SET, True)] and pg.locator("#buildsets").count() == 0
    assert rig.state()["open_set"] == MIX_SET
    assert pg.locator("#sheet.on").count() == 0
    pg.click('#tabs button[data-t="desk"]')  # the desk is for another set now: the way back is on the Hear bar
    assert "HW002_121_pp_finish" in pg.locator("#opendesk").inner_text()


def test_set_open_opens_only_the_two_sets_and_never_an_unsaved_front_set(song_rig, monkeypatch):  # noqa: F811
    rig = song_rig.rig
    asked: list[str] = []
    monkeypatch.setattr(jobs.session, "open_set", lambda client, name, **kw: asked.append(name) or 1.0)
    open_in_live(rig, "HW002_121_pp_finish")
    assert rig.command("set.open", {"name": "someone_elses_set"})[0] == 400
    assert rig.desk.bus.submit(Command("set.open", "agent", {"name": MIX_SET}))[0] == 403
    open_in_live(rig, "")  # a set with no file: saving it first is not possible, so nothing is opened over it
    code, reply = rig.command("set.open", {"name": MIX_SET})
    assert code == 409 and "Save it in Live" in reply["error"] and asked == []
    open_in_live(rig, "HW002_121_pp_finish")
    code, reply = rig.command("set.open", {"name": MIX_SET})
    assert code == 200 and reply["saved"] == "HW002_121_pp_finish" and asked == [MIX_SET]


# ---- 4: the spectrum turns itself on ------------------------------------------------------------------------------------


def fake_meter_tool(rig, monkeypatch, fail: str = ""):
    """The desk's real meter tool, with the one step that needs Live's browser stood in for."""
    from zpkt.live.testing import devices

    tool = rig.desk.meter_tool()

    def install(live, log=print):
        if fail:
            raise tool.MeterError(fail)
        rig.live.song.master_track._add_device(devices.make("Utility", name=tool.NAME))
        return True

    monkeypatch.setattr(tool, "install", install)
    return tool


def test_the_spectrum_has_one_action_that_puts_the_device_on_main(browser, rig, monkeypatch):
    tool = fake_meter_tool(rig, monkeypatch)
    pg = open_lead(browser, rig)
    assert (
        "desk meter" not in pg.locator("#htop").inner_text() and "No spectrum" not in pg.locator("#htop").inner_text()
    )
    button = pg.locator("#meteron")
    assert button.inner_text().strip() == "Turn on" and button.bounding_box()["height"] >= 44
    before = len(rig.desk.history.entries)
    button.click()
    wait_for(lambda: tool.present(rig.conn))
    wait_for(lambda: len(rig.desk.history.entries) == before + 1)
    rig.meter.send(osc_spec([0.1] * len(meter.centers())))  # the device is there: it sends
    pg.wait_for_selector("#spec:not(.act) i")
    assert pg.locator("#meteron").count() == 0
    entry = rig.desk.history.entries[-1]
    assert entry["who"] == "you" and entry["moves"][0]["label"] == "Spectrum"
    assert rig.get("/api/hear")[1]["changed"] == 0  # a device for measuring is no change to the mix
    assert rig.command("history.undo")[0] == 200  # a normal move: undo takes the device off again
    assert not tool.present(rig.conn) and rig.state()["meter"] is False
    pg.evaluate("window.zpkt.S.meterAt = Date.now() - 60000")  # its bars stop
    pg.wait_for_selector("#meteron")
    assert pg.errors == []  # type: ignore[attr-defined]


def test_a_spectrum_that_will_not_turn_on_says_so_with_retry_and_no_device_no_live_shows_nothing(
    browser, rig, monkeypatch
):
    fake_meter_tool(rig, monkeypatch, fail="Live's browser does not show the meter yet")
    pg = open_lead(browser, rig)
    pg.click("#meteron")
    pg.wait_for_selector("#meterfail")
    assert pg.locator("#meterfail").inner_text() == "Failed" and pg.locator("#meteron").inner_text().strip() == "Retry"
    assert "browser" in pg.locator("#meterfail").get_attribute("title")
    pg.evaluate("window.zpkt.S.mjob = null")
    rig.desk.set_state(None, "Live does not answer (gone)")  # nothing to press when Live is not there
    pg.wait_for_function("!document.querySelector('#spec')")


# ---- 5: "N changed" has a base, and it is named -------------------------------------------------------------------------


def test_changed_counts_from_the_last_checkpoint_saved_or_gone_back_to(browser, rig):
    pg = open_lead(browser, rig)
    rig.command("mix.set", {"norms": [[VOL, 0.3]]})
    pg.wait_for_function("document.querySelector('#chgn').textContent === '1 changed'")
    assert rig.command("history.checkpoint", {"name": "mara clean kick", "new": True})[0] == 200
    pg.wait_for_function("document.querySelector('#chgn').textContent === '0 changed'")  # zero right after a save
    assert pg.locator("#chgbase").inner_text().strip() == "mara clean kick"  # and it says what it counts from
    rig.command("mix.set", {"norms": [[GAIN, 0.7]]})
    pg.wait_for_function("document.querySelector('#chgn').textContent === '1 changed'")
    rig.command("history.checkpoint", {"name": "later", "new": True})
    rig.command("mix.set", {"norms": [[VOL, 0.6]]})
    pg.wait_for_function("document.querySelector('#chgbase').textContent.trim() === 'later'")
    back = pg.locator('#hrows [data-back="mara clean kick"]')
    if not back.count():  # the rows are paged: it is on the part after
        pg.click('#hpgs [data-histstep="1"]')
    back.click()
    pg.wait_for_function("document.querySelector('#chgbase').textContent.trim() === 'mara clean kick'")
    assert pg.locator("#chgn").inner_text() == "0 changed"  # the walkthrough's "1 changed" after going back
    hear = rig.get("/api/hear")[1]
    assert hear["changed"] == 0 and hear["base"] == "mara clean kick"
    assert pg.locator("#chgpill").bounding_box()["height"] >= 44
    pg.click("#chgpill")  # a tap on it brings History forward
    assert "ping" in pg.locator("#histdock").get_attribute("class")
    phone = browser.new_page(viewport={"width": 390, "height": 800})
    phone.goto(rig.url + "/app/")
    phone.wait_for_selector("#chgpill")
    phone.click("#chgpill")
    phone.wait_for_selector("#sheet.on #hrows")


# ---- 6: History on a desktop and on a phone -----------------------------------------------------------------------------


def old_entries(rig, days: float, count: int) -> None:
    """Changes from an earlier sitting, as the history file would hold them."""
    h = rig.desk.history
    at = time.time() - days * 86400
    with h.lock:
        for i in range(count):
            h.seq += 1
            move = {"key": VOL, "label": "Kick bus volume", "from": ["-3.0 dB", 0.7], "to": ["-2.0 dB", 0.72]}
            h.entries.insert(i, {"k": "move", "moves": [move], "who": "you", "id": h.seq, "at": at + i})
        h.pos += count


def test_history_is_docked_on_a_desktop_and_the_knobs_stay_in_reach(browser, rig):
    old_entries(rig, 2, 3)
    pg = open_lead(browser, rig)
    dock = pg.locator("#histdock").bounding_box()
    panel = pg.locator("#panel").bounding_box()
    assert dock["x"] >= panel["x"] + panel["width"] and dock["height"] >= 120  # beside the controls, never over them
    assert pg.locator("#khist").is_hidden() and pg.locator("#sheet.on").count() == 0
    pg.locator(ctl(GAIN) + " .w").focus()
    pg.keyboard.press("ArrowUp")
    pg.wait_for_selector("#hrows > .he.row")  # the row fills in while the knob turns
    assert "Tone" in rows(pg)[0] and "you" in rows(pg)[0]
    # an earlier day is folded under its heading, and its rows are not "you"
    day = pg.locator("#hrows .hday")
    assert day.count() == 1 and day.get_attribute("aria-expanded") == "false" and day.inner_text().split()[-1] == "3"
    assert pg.locator("#hrows .he.old").count() == 0
    day.click()
    assert pg.locator("#hrows .he.old").count() == 3 and pg.locator("#hrows .he.old .who").count() == 0
    # strict time order: an undone change stays where it happened, a checkpoint saved after it sits above it
    pg.click("#kundo")
    pg.wait_for_selector("#hrows > .he.undone")
    rig.command("history.checkpoint", {"name": "after the undo", "new": True})
    pg.wait_for_selector('#hrows .he.cp[data-cp="after the undo"]')
    top = pg.locator("#hrows > .he")
    assert "after the undo" in top.nth(0).inner_text() and "undone" in top.nth(1).inner_text()
    assert pg.errors == []  # type: ignore[attr-defined]


def test_on_a_phone_history_is_a_sheet_and_a_tap_outside_closes_it_and_reaches_the_control(browser, rig):
    pg = open_lead(browser, rig, width=390, height=800)
    assert pg.locator("#histdock").is_hidden()
    pg.click("#khist")
    pg.wait_for_selector("#sheet.on #hrows")
    assert pg.evaluate("getComputedStyle(document.querySelector('#scrim')).pointerEvents") == "none"
    pg.wait_for_function("getComputedStyle(document.querySelector('#sheet')).transform === 'none'")  # it has come up
    x, y = centre(pg, RATIO)  # knob 1, in the top row of the map
    assert y < pg.locator("#sheet").bounding_box()["y"]  # a control the sheet does not cover
    pg.mouse.click(x, y)  # one tap: the sheet goes, and the control has the tap
    pg.wait_for_selector("#sheet:not(.on)")
    assert pg.evaluate("document.activeElement.closest('.mc')?.dataset.key") == RATIO


# ---- 7: knobs ----------------------------------------------------------------------------------------------------------


def test_a_mouse_moves_a_knob_from_the_first_pixels_and_a_finger_loses_no_travel(browser, rig):
    pg = open_lead(browser, rig)
    start = place(pg, GAIN)
    x, y = centre(pg, GAIN)
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.wait_for_timeout(150)  # a hand at rest, then a small move: it counts in full
    pg.mouse.move(x, y - 3)
    assert place(pg, GAIN) > start  # the walkthrough's 8 px that did nothing
    assert pg.locator("#bubble").inner_text() == shown(pg, GAIN)  # and it is shown as it happens
    pg.mouse.up()
    assert pg.locator("#bubble").is_hidden() and pg.evaluate("document.querySelector('#bubble').textContent") == ""
    settled(pg, GAIN)
    # a finger: 3 px are not yet a move; once it is one, the travel counts from where the finger came down
    start = place(pg, GAIN)
    touch = """([sel, dy, type]) => { const w = document.querySelector(sel), r = w.getBoundingClientRect();
      w.dispatchEvent(new PointerEvent(type, {pointerType: 'touch', pointerId: 7, bubbles: true, cancelable: true,
        clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 + dy})); }"""
    sel = ctl(GAIN) + " .w"
    pg.evaluate(touch, [sel, 0, "pointerdown"])
    pg.wait_for_timeout(150)
    pg.evaluate(touch, [sel, -3, "pointermove"])
    assert place(pg, GAIN) == start
    pg.wait_for_timeout(150)
    pg.evaluate(touch, [sel, -20, "pointermove"])
    moved = place(pg, GAIN) - start
    assert 0.09 < moved < 0.11, moved  # 20 px of 200, all of them: none lost to the first 4
    pg.evaluate(touch, [sel, -20, "pointerup"])
    settled(pg, GAIN)
    assert pg.errors == []  # type: ignore[attr-defined]


def test_steps_are_round_units_and_seven_db_can_be_reached_and_typed(browser, rig):
    pg = open_lead(browser, rig)
    rig.command("mix.set", {"norms": [[GAIN, 0.7497]]})  # an odd value, as a drag used to leave it
    pg.wait_for_function(f"!document.querySelector({json.dumps(ctl(GAIN) + ' .v')}).textContent.endsWith('00 dB')")
    odd = float(shown(pg, GAIN).split()[0])
    pg.locator(ctl(GAIN) + " .w").focus()
    pg.keyboard.press("ArrowDown")  # half a dB down, onto a round value
    down = float(shown(pg, GAIN).split()[0])
    assert down == pytest.approx(round((odd - 0.5) * 2) / 2) and shown(pg, GAIN).endswith("0 dB")
    pg.keyboard.press("Shift+ArrowUp")  # a tenth
    assert float(shown(pg, GAIN).split()[0]) == pytest.approx(down + 0.1)
    pg.keyboard.press("PageUp")
    assert float(shown(pg, GAIN).split()[0]) == pytest.approx(
        round((down + 0.1 + 3.0) / 3) * 3
    )  # onto a multiple of 3 dB
    settled(pg, GAIN)
    drag(pg, GAIN, -17)  # a drag lands on tenths of a dB
    text = shown(pg, GAIN)
    assert round(float(text.split()[0]) * 10) == pytest.approx(float(text.split()[0]) * 10)
    settled(pg, GAIN)
    # the number is the place to type: it looks it, and a click opens the field there
    num = pg.locator(ctl(GAIN) + " .v")
    assert (
        "ed" in pg.locator(ctl(GAIN)).get_attribute("class").split()
        and num.evaluate("e => getComputedStyle(e).cursor") == "text"
    )
    num.click()
    field = pg.locator(ctl(GAIN) + " .vt")
    field.wait_for()
    field.fill("7")
    pg.keyboard.press("Enter")
    settled(pg, GAIN)
    assert shown(pg, GAIN) == "7.00 dB"
    num.click()
    pg.locator(ctl(GAIN) + " .vt").fill("2")
    pg.keyboard.press("Escape")
    assert pg.locator(".vt").count() == 0 and shown(pg, GAIN) == "7.00 dB"
    assert pg.errors == []  # type: ignore[attr-defined]


def test_a_frequency_steps_by_a_semitone(browser, rig):
    spec = {"title": "Tone", "groups": [{"name": "g", "controls": [{"target": FREQ, "label": "Freq"}]}]}
    assert rig.desk.bus.submit(Command("page.make", "agent", {"spec": spec}))[0] == 200
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + "/app/")
    pg.wait_for_function(f"window.zpkt?.S.scales[{json.dumps(FREQ)}]?.kind === 'continuous'")

    def hz() -> float:
        at = f"+document.querySelector({json.dumps(ctl(FREQ))}).dataset.n"
        return float(pg.evaluate(f"window.zpkt.valueAt({json.dumps(FREQ)}, {at}).x"))

    was = hz()
    pg.locator(ctl(FREQ) + " .w").focus()
    pg.keyboard.press("ArrowUp")
    assert hz() / was == pytest.approx(2 ** (1 / 12), rel=0.02)
    pg.keyboard.press("PageUp")
    assert hz() / was == pytest.approx(2 ** (13 / 12), rel=0.03)  # an octave more


# ---- 8: a link to a Page shows it loading -------------------------------------------------------------------------------


def test_a_link_to_a_page_shows_its_title_loading_and_keeps_the_address(browser, rig, monkeypatch):
    spec = {"title": "Drop hats: brightness", "groups": [{"name": "Bus", "controls": [{"target": VOL}]}]}
    code, reply = rig.command("page.make", {"spec": spec})
    assert code == 200, reply
    pid = reply["id"]
    rig.command("page.arm", {"page": 0})
    go, real = threading.Event(), rig.desk.call

    def call(code, *args, **kwargs):
        if "DESK.arm(" in code:
            go.wait(10)
        return real(code, *args, **kwargs)

    monkeypatch.setattr(rig.desk, "call", call)
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + f"/app/#page={pid}")
    pg.wait_for_function("document.querySelector('#pagename')?.textContent === 'Drop hats: brightness'", timeout=3000)
    assert pg.locator("#pgwait").inner_text() == "Loading"
    assert "is-loading" in pg.locator("#main").get_attribute("class")
    assert pg.evaluate("location.hash") == f"#page={pid}"  # until it is open
    assert pg.evaluate("window.zpkt.S.state.page") == 0  # Live has not changed the page yet
    go.set()
    pg.wait_for_function("location.hash === '#desk'")
    assert pg.locator("#pgwait").count() == 0 and pg.locator("#pagename").inner_text() == "Drop hats: brightness"
    assert "is-loading" not in pg.locator("#main").get_attribute("class")


# ---- 9: the Song has a bar ruler ----------------------------------------------------------------------------------------


def test_the_song_has_a_ruler_with_sections_the_loop_and_the_playhead(browser, song_rig):  # noqa: F811
    rig = song_rig.rig
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#ruler .sec")
    view = rig.command("song.show")[1]
    assert [s["start"] for s in view["sections"]] == [0, 16, 24] and sum(s["len"] for s in view["sections"]) == view[
        "bars"
    ]
    assert pg.locator("#ruler .sec").count() == 3
    numbers = pg.locator("#ruler .rt > .bn").all_inner_texts()
    assert numbers[0] == "1" and "17" in numbers and "25" in numbers  # bar numbers, one at every section's start
    ruler, lane = pg.locator("#ruler .rt").bounding_box(), pg.locator("#lanes .lane .tr").first.bounding_box()
    assert abs(ruler["x"] - lane["x"]) < 1 and abs(ruler["width"] - lane["width"]) < 1  # bar for bar over the lanes
    rig.send({"t": "loop", "loop": "drop", "start": 64.0, "length": 96.0})
    pg.wait_for_selector("#songlp")
    assert "17–40" in pg.locator("#songloop").inner_text()
    lp = pg.locator("#songlp").bounding_box()
    assert lp["x"] == pytest.approx(ruler["x"] + ruler["width"] * 16 / 40, abs=2)
    assert pg.locator("#looppill").inner_text().strip() == "17–40"  # the Hear bar says the span, not only the word
    assert "17 to 40" in pg.locator("#looppill").get_attribute("aria-label")
    rig.send({"t": "pos", "b": 80.0, "p": True})  # bar 21
    pg.wait_for_function("!document.querySelector('#songhead').hidden")
    pg.wait_for_function("document.querySelector('#barno').textContent.startsWith('bar 21')")
    head = pg.locator("#songhead").bounding_box()
    assert head["x"] + head["width"] / 2 == pytest.approx(ruler["x"] + ruler["width"] * 20 / 40, abs=2)
    # the paragraph is gone: the buttons that play sketches in the browser carry a badge
    assert "rendered loops" not in pg.locator("#song").inner_text()
    assert pg.locator('#song [data-sheet="mix"] .bdg').inner_text().lower() == "sketch"
    assert pg.locator('#song [data-sheet="transitions"] .bdg').count() == 1
    assert pg.locator("#song .sketch").count() == 0


# ---- 10: nothing is made anew on an event; the bubble holds no stale text ------------------------------------------------


def test_the_controls_keep_their_elements_across_events(browser, rig):
    pg = open_lead(browser, rig)
    pg.evaluate(
        f"""() => {{ window.kept = {{knob: document.querySelector({json.dumps(ctl(GAIN))}), w: document.querySelector({json.dumps(ctl(GAIN) + " .w")}),
            play: document.querySelector('#kplay'), name: document.querySelector('#setname'), chg: document.querySelector('#chgpill')}}; }}"""
    )
    pg.locator(ctl(GAIN) + " .w").focus()
    rig.command("mix.set", {"norms": [[VOL, 0.31]]})  # a value from elsewhere, a history event, a hear event
    rig.command("mix.set", {"norms": [[GAIN, 0.61]]})
    for beat in (4.0, 8.0, 12.0):
        rig.send({"t": "pos", "b": beat, "p": False})
    rig.meter.send(osc_spec([0.1] * len(meter.centers())))
    pg.wait_for_function("document.querySelector('#barno').textContent.startsWith('bar 4')")
    pg.wait_for_function(f"Math.abs(document.querySelector({json.dumps(ctl(GAIN))}).dataset.n - 0.61) < 0.001")
    same = pg.evaluate(
        f"""() => ({{knob: window.kept.knob === document.querySelector({json.dumps(ctl(GAIN))}), w: window.kept.w === document.activeElement,
            play: window.kept.play === document.querySelector('#kplay'), name: window.kept.name === document.querySelector('#setname'),
            chg: window.kept.chg === document.querySelector('#chgpill')}})"""
    )
    assert same == {"knob": True, "w": True, "play": True, "name": True, "chg": True}
    assert (
        pg.locator("#bubble").is_hidden()
        and pg.evaluate("document.querySelector('#bubble').getAttribute('aria-hidden')") == "true"
    )
    assert pg.errors == []  # type: ignore[attr-defined]
