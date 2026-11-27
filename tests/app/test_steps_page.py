"""Steps on the Song tab, in WebKit on a phone (375 x 812), against the app on FakeLive: a drum track from the kit
picker, the Steps screen, a tap on a pad as a note in Live's Arrangement clip. Nothing scrolls."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from zpkt.live import steps

playwright_sync = pytest.importorskip("playwright.sync_api")

PHONE = {"width": 375, "height": 812}
DESKTOP = {"width": 1200, "height": 800}
KICK, SNARE = 36, 38


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(steps.time, "sleep", lambda s: None)


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def song(browser, rig, viewport=PHONE):
    pg = browser.new_page(viewport=viewport)
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors  # type: ignore[attr-defined]
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#lanes .lane .rg")
    return pg


def no_scroll(pg) -> bool:
    return pg.evaluate(
        "document.documentElement.scrollHeight <= innerHeight && document.documentElement.scrollWidth <= innerWidth"
        " && [...document.querySelectorAll('#song, #song *')].every(e => e.scrollHeight <= e.clientHeight + 1 ||"
        " getComputedStyle(e).overflowY === 'visible' || getComputedStyle(e).overflowY === 'hidden')"
    )


def notes(rig, name="Drums"):
    track = rig.track(name)
    return sorted((c.start_time, n.pitch, n.start_time, n.velocity) for c in track.arrangement_clips for n in c._notes)


def make_drums(pg, rig, kit="909 Core Kit"):
    """The one key the Song shows with no MIDI track, the picker, a kit: Steps opens on the new track."""
    pg.locator('#songnew [data-st="pick"]').click()
    pg.wait_for_selector("#st-kits [data-kit]")
    pg.locator(f'#st-kits [data-kit="{kit}"]').click()
    pg.wait_for_selector("#steps .st-pad:not([disabled])")


def test_a_drum_track_from_the_picker_then_taps_on_pads_are_notes_in_live(browser, rig):
    pg = song(browser, rig)
    key = pg.locator('#songnew [data-st="pick"]')
    assert key.bounding_box()["height"] >= 43.9
    key.click()
    pg.wait_for_selector("#st-kits [data-kit]")
    kits = pg.locator("#st-kits [data-kit]:visible")
    assert kits.all_inner_texts() == ["606 Core Kit", "707 Core Kit", "808 Core Kit", "909 Core Kit"]
    assert all(
        b["height"] >= 43.9 for b in kits.evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())")
    )
    assert no_scroll(pg)
    kits.nth(3).click()
    pg.wait_for_selector("#steps .st-pad:not([disabled])")
    first_monitor = next(i for i, t in enumerate(rig.live.song.tracks) if t.name.startswith("mon "))
    assert rig.live.song.tracks[first_monitor - 1].name == "Drums"  # made in front of the monitor tracks
    assert rig.track("Drums").devices[0].name == "909 Core Kit"

    # the Steps screen: the track, the bar under the playhead, a row per sound, 16 pads in two banks of 8
    assert pg.locator("#steps .st-bar .sn b").inner_text() == "Drums"
    assert pg.locator("#st-barn").inner_text() == "Bar 1"
    assert pg.locator("#st-ov .st-row:visible .n").all_inner_texts() == ["Kick", "Rim", "Snare", "Clap", "Hat", "Open"]
    assert pg.locator("#st-name").inner_text() == "Kick"  # the first sound is the chosen one
    pads = pg.locator("#steps .st-pad")
    assert pads.count() == 16 and pads.all_inner_texts() == [str(n) for n in range(1, 17)]
    sizes = pads.evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())")
    assert all(b["width"] >= 38 and b["height"] >= 38 for b in sizes)
    assert sizes[0]["y"] == sizes[7]["y"] < sizes[8]["y"] == sizes[15]["y"]  # pads A over pads B
    assert pg.locator("#steps .st-pad.beat").evaluate_all("els => els.map(e => e.dataset.k)") == ["0", "4", "8", "12"]
    for k in pg.locator("#steps .st-bar .key").evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())"):
        assert k["width"] >= 43.9 and k["height"] >= 43.9
    assert no_scroll(pg)

    # a tap is a note: lit at once on the page, and in Live's clip
    pads.nth(0).click()
    pg.wait_for_selector('#steps .st-pad[data-k="0"].on')
    pads.nth(4).click()
    wait_for(lambda: len(notes(rig)) == 2)
    assert notes(rig) == [(0.0, KICK, 0.0, 100), (0.0, KICK, 1.0, 100)]
    assert pg.locator("#st-ov .st-row.sel .c.on").count() == 2  # the overview shows it too
    # another sound: its row is chosen, the pads are its steps
    pg.locator('#st-ov .st-row[data-pitch="38"]').click()
    assert pg.locator("#st-name").inner_text() == "Snare" and pg.locator("#steps .st-pad.on").count() == 0
    pads.nth(12).click()
    wait_for(lambda: len(notes(rig)) == 3)
    assert (0.0, SNARE, 3.0, 100) in notes(rig)
    # a second tap takes the note away again
    pads.nth(12).click()
    wait_for(lambda: len(notes(rig)) == 2)
    pg.wait_for_selector('#steps .st-pad[data-k="12"]:not(.on)')

    # the next bar is another pattern: empty; back, and the kick is there again (read from Live)
    pg.locator('#steps [data-st="bar"][data-by="1"]').click()
    pg.wait_for_function("document.querySelector('#st-barn').textContent === 'Bar 2'")
    pg.wait_for_function("!document.querySelector('#steps').dataset.loading")
    assert pg.locator("#st-ov .c.on").count() == 0
    pg.locator('#steps [data-st="bar"][data-by="-1"]').click()
    pg.wait_for_function("document.querySelectorAll('#st-ov .c.on').length === 2")

    # close: the lanes again, with a lane for the drum track and its region; the strip has the Steps key
    pg.locator('#steps [data-st="close"]').click()
    pg.wait_for_selector('#lanes .lane[data-name="Drums"] .rg')
    assert pg.locator("#songnew").inner_text() == ""  # the set has a MIDI track now
    assert pg.locator("#songsel .sn").inner_text() == "Drums"
    steps_key = pg.locator('#songsel [data-st="open"]')
    assert steps_key.bounding_box()["height"] >= 43.9
    steps_key.click()
    pg.wait_for_function("document.querySelectorAll('#st-ov .c.on').length === 2")
    assert no_scroll(pg) and pg.errors == []


def test_clips_in_the_way_are_a_state_of_the_bar_and_its_pads_are_off(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(4.0, 8.0)\nresult = 1")
    pg.locator('#steps [data-st="bar"][data-by="1"]').click()  # bar 2: a two-bar clip lies over it
    pg.wait_for_selector("#st-barn[data-blocked]")
    assert pg.locator("#steps .st-pad:disabled").count() == 16
    assert pg.locator("#steps").inner_text().count("in the way") == 0  # a state, not a sentence
    pg.locator('#steps [data-st="bar"][data-by="-1"]').click()
    pg.wait_for_selector("#st-barn:not([data-blocked])")
    pg.wait_for_selector("#steps .st-pad:not([disabled])")
    assert pg.errors == []


def test_steps_fits_a_desktop_too(browser, rig):
    pg = song(browser, rig, DESKTOP)
    make_drums(pg, rig)
    assert no_scroll(pg)
    box = pg.locator("#steps .st-ml").bounding_box()
    assert box["y"] + box["height"] <= 800 and pg.locator("#st-ov .st-row:visible").count() == 6
    assert pg.errors == []


def test_the_focus_reaches_a_second_page_the_loop_key_loops_the_bar_and_the_playhead_step_is_outlined(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    other = browser.new_page(viewport=DESKTOP)  # a second page: it hears what the first has in hand
    other.goto(rig.url + "/app/#song")
    other.wait_for_function("window.zpkt && window.zpkt.S.state")
    wait_for(lambda: rig.state()["steps"] is not None)
    focus = rig.state()["steps"]
    assert (focus["track"], focus["bar"], focus["bars"], focus["name"], focus["steps"]) == (
        "Drums",
        1,
        1,
        "Kick",
        [0] * 16,
    )
    pg.locator("#steps .st-pad").nth(4).click()
    other.wait_for_function("window.zpkt.S.state.steps && window.zpkt.S.state.steps.steps[4] === 100")
    pg.locator('#st-ov .st-row[data-pitch="38"]').click()
    other.wait_for_function("window.zpkt.S.state.steps.name === 'Snare'")
    assert rig.state()["steps"]["pitch"] == SNARE

    # a step flipped by another hand (the MiniLab's pad, later) shows on the page
    f = rig.state()["steps"]
    press = {k: f[k] for k in ("track", "bar", "bars", "pitch", "velocity", "length", "swing")}
    assert rig.desk.bus.submit(steps_command("steps.toggle", {**press, "step": 9}, "minilab"))[0] == 200
    pg.wait_for_selector('#steps .st-pad[data-k="9"].on')
    # and another hand choosing the sound moves the page to it
    rig.desk.bus.submit(steps_command("steps.focus", {"pitch": KICK}, "minilab"))
    pg.wait_for_function("document.querySelector('#st-name').textContent === 'Kick'")
    assert pg.locator("#steps .st-pad.on").evaluate_all("els => els.map(e => e.dataset.k)") == ["4"]

    # the loop key: Live loops the bar in hand; the lit key again puts the loop back
    song_ = rig.live.song
    before = (song_.loop, song_.loop_start, song_.loop_length)
    key = pg.locator('#steps [data-st="loop"]')
    key.click()
    wait_for(lambda: (song_.loop, song_.loop_start, song_.loop_length) == (True, 0.0, 4.0))
    pg.wait_for_selector('#steps [data-st="loop"].on')
    pg.locator('#steps [data-st="bar"][data-by="1"]').click()  # the loop follows the bar in hand
    wait_for(lambda: (song_.loop_start, song_.loop_length) == (4.0, 4.0))
    pg.wait_for_selector('#steps [data-st="loop"].on')
    pg.locator('#steps [data-st="bar"][data-by="-1"]').click()
    wait_for(lambda: song_.loop_start == 0.0)
    pg.wait_for_selector('#steps [data-st="loop"].on')

    # the step under Live's playhead is outlined while it plays inside the pattern
    rig.send({"t": "pos", "b": 1.3, "p": True})  # beat 1.3 of bar 1: the 6th sixteenth
    pg.wait_for_selector('#steps .st-pad[data-k="5"].ph')
    rig.send({"t": "pos", "b": 3.76, "p": True})
    pg.wait_for_selector('#steps .st-pad[data-k="15"].ph')
    assert pg.locator("#steps .st-pad.ph").count() == 1
    rig.send({"t": "pos", "b": 9.0, "p": True})  # another bar: no pad
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.ph').length === 0")
    rig.send({"t": "pos", "b": 1.0, "p": False})  # stopped: none either
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.ph').length === 0")

    key.click()
    wait_for(lambda: (song_.loop, song_.loop_start, song_.loop_length) == before)
    pg.wait_for_selector('#steps [data-st="loop"]:not(.on)')
    # closing Steps lets the focus go
    pg.locator('#steps [data-st="close"]').click()
    wait_for(lambda: rig.state()["steps"] is None)
    other.wait_for_function("window.zpkt.S.state.steps === null")
    assert no_scroll(pg) and pg.errors == []


def steps_command(kind, args, who):
    from zpkt.app.bus import Command

    return Command(kind, who, args)


def lane_clips(rig, name="Drums"):
    return [(c.start_time / 4 + 1, c.end_time / 4 + 1) for c in rig.track(name).arrangement_clips]


def cell_kinds(pg) -> dict[int, str]:
    """{bar: its cell's kind} for the cells that are not empty: p (the pattern), o (another clip), x (in the way)."""
    found = pg.locator("#lanes .lane.paint .st-cell").evaluate_all(
        "els => els.map(e => [+e.dataset.bar, ['p', 'o', 'x'].find(k => e.classList.contains(k)) || ''])"
    )
    return {bar: kind for bar, kind in found if kind}


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_paint_by_tap_and_by_drag_erase_and_the_colours_say_what_each_bar_holds(browser, rig, viewport):
    pg = song(browser, rig, viewport)
    make_drums(pg, rig)
    for k in (0, 4, 8, 12):
        pg.locator("#steps .st-pad").nth(k).click()
    wait_for(lambda: len(notes(rig)) == 4)
    pg.locator('#steps [data-st="paint"]').click()  # from Steps: paint this pattern
    pg.wait_for_selector("#lanes .lane.paint .st-cell.p.src")
    assert rig.state()["steps"] is None  # Steps is closed: nothing is in hand
    lane = pg.locator("#lanes .lane.paint")
    assert lane.get_attribute("data-name") == "Drums" and 50 <= lane.bounding_box()["height"] <= 54
    assert pg.locator("#lanes .lane.paint .st-cell").count() == 40  # one cell a bar across the song's 40 bars
    assert cell_kinds(pg) == {1: "p"}
    # the strip: the pattern small, the track, Steps, Erase, Paint lit
    assert pg.locator("#songsel #st-thumb i.on").count() == 4 and pg.locator("#songsel .sn").inner_text() == "Drums"
    keys = pg.locator("#songsel button")
    assert keys.evaluate_all("els => els.map(e => [e.dataset.st, e.getAttribute('aria-pressed')])") == [
        ["steps", None],
        ["erase", "false"],
        ["paint", "true"],
    ]
    assert all(
        b["height"] >= 43.9 and b["width"] >= 43.9
        for b in keys.evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())")
    )
    assert no_scroll(pg)

    def cell(bar):
        return pg.locator(f'#lanes .lane.paint .st-cell[data-bar="{bar}"]')

    def middle(bar):
        box = cell(bar).bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    # a tap paints one bar
    pg.mouse.click(*middle(3))
    wait_for(lambda: lane_clips(rig) == [(1, 2), (3, 4)])
    cell(3).and_(pg.locator(".p")).wait_for()
    # a drag paints every bar it crosses, as one command
    asked = len(rig.desk.bus.log)
    pg.mouse.move(*middle(5))
    pg.mouse.down()
    pg.mouse.move(*middle(8), steps=5)
    pg.mouse.up()
    wait_for(lambda: lane_clips(rig) == [(1, 2), (3, 4), (5, 6), (6, 7), (7, 8), (8, 9)])
    assert wait_for(lambda: [e["kind"] for e in list(rig.desk.bus.log)[asked:] if e["kind"] == "steps.paint"]) == [
        "steps.paint"
    ]
    pg.wait_for_function("document.querySelectorAll('#lanes .lane.paint .st-cell.p').length === 6")
    assert (
        pg.locator("#lanes .lane.sel").get_attribute("data-name") == "Drums"
    )  # a tap on a cell does not let the lane go

    # another pattern of the same length is grey; a longer clip in the way is hatched (and is never cut)
    rig.desk.bus.submit(
        steps_command("steps.toggle", {"track": "Drums", "bar": 10, "bars": 1, "pitch": SNARE, "step": 4}, "cli")
    )
    cell(10).and_(pg.locator(".o")).wait_for()
    pg.wait_for_timeout(400)  # the pager says "a clip changed" at most three times a second
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(48.0, 8.0)\nresult = 1")
    cell(10).and_(pg.locator(".o")).wait_for()
    cell(13).and_(pg.locator(".x")).wait_for()
    assert cell_kinds(pg) == {1: "p", 3: "p", 5: "p", 6: "p", 7: "p", 8: "p", 10: "o", 13: "x", 14: "x"}
    pg.mouse.click(*middle(13))  # painting onto it changes nothing
    pg.wait_for_timeout(150)
    assert (13, 15) in lane_clips(rig) and cell_kinds(pg)[13] == "x"

    # Erase lit: the same gesture erases
    pg.locator('#songsel [data-st="erase"]').click()
    pg.wait_for_selector('#songsel [data-st="erase"].on')
    pg.mouse.move(*middle(6))
    pg.mouse.down()
    pg.mouse.move(*middle(7), steps=3)
    pg.mouse.up()
    wait_for(lambda: lane_clips(rig) == [(1, 2), (3, 4), (5, 6), (8, 9), (10, 11), (13, 15)])
    pg.wait_for_function("document.querySelectorAll('#lanes .lane.paint .st-cell.p').length === 4")
    pg.locator('#songsel [data-st="erase"]').click()
    pg.wait_for_selector('#songsel [data-st="erase"]:not(.on)')

    # the playhead and the loop stay on the Song while painting
    rig.send({"t": "loop", "loop": "drop", "start": 64.0, "length": 96.0})
    rig.send({"t": "pos", "b": 80.0, "p": True})
    pg.wait_for_selector("#songlp")
    pg.wait_for_function("!document.querySelector('#songhead').hidden")
    assert no_scroll(pg)

    # Steps again: the same pattern; and the lit Paint key ends painting
    pg.locator('#songsel [data-st="steps"]').click()
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 4")
    assert pg.locator("#st-barn").inner_text() == "Bar 1"
    pg.locator('#steps [data-st="paint"]').click()
    pg.wait_for_selector("#lanes .lane.paint")
    pg.locator('#songsel [data-st="paint"]').click()
    pg.wait_for_function("!document.querySelector('#lanes .lane.paint')")
    assert pg.locator('#songsel [data-songflag="solo"]').count() == 1  # the strip is the track's own again
    assert pg.locator('#lanes .lane[data-name="Drums"] .rg').count() == 6
    assert no_scroll(pg) and pg.errors == []


def clip_notes(rig, name="Drums"):
    """Every note of the track as (pitch, beat in the song, duration, velocity)."""
    track = rig.track(name)
    return sorted(
        (n.pitch, round(c.start_time + n.start_time, 4), round(n.duration, 4), n.velocity)
        for c in track.arrangement_clips
        for n in c._notes
    )


def turn(pg, what: str, dy: float) -> None:
    box = pg.locator(f'#st-knobs .mc[data-key="{what}"] .w').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x, y + dy, steps=6)
    pg.mouse.up()


def knob_text(pg, what: str) -> str:
    return pg.locator(f'#st-knobs .mc[data-key="{what}"] .v').inner_text()


def test_the_knobs_change_the_step_in_hand_swing_moves_the_pattern_and_clear_empties_it(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    pads = pg.locator("#steps .st-pad")
    knobs = pg.locator("#st-knobs .mc.knob")
    assert knobs.locator(".l").all_inner_texts() == ["Velocity", "Length", "Swing"]
    assert [knob_text(pg, k) for k in ("velocity", "length", "swing")] == ["100", "1/16", "0%"]
    assert all(
        b["height"] >= 43.9
        for b in pg.locator("#st-knobs .w").evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())")
    )
    assert no_scroll(pg)

    # the step touched last is the one Velocity and Length change
    pads.nth(0).click()
    pg.wait_for_selector('#steps .st-pad[data-k="0"].on.last')
    turn(pg, "velocity", 80)  # down: softer
    softer = int(knob_text(pg, "velocity"))
    assert softer < 80
    wait_for(lambda: clip_notes(rig) == [(KICK, 0.0, 0.25, softer)])
    pg.wait_for_selector('#steps .st-pad[data-k="0"].soft')
    pg.locator('#st-knobs .mc[data-key="length"] .w').focus()
    pg.keyboard.press("ArrowUp")  # the next stop: an eighth
    assert knob_text(pg, "length") == "1/8"
    wait_for(lambda: clip_notes(rig) == [(KICK, 0.0, 0.5, softer)])
    # and a new step gets what the knobs say
    pads.nth(3).click()
    wait_for(lambda: clip_notes(rig) == [(KICK, 0.0, 0.5, softer), (KICK, 0.75, 0.5, softer)])
    pg.wait_for_selector('#steps .st-pad[data-k="3"].on.last')
    assert pg.locator("#steps .st-pad.last").count() == 1

    # Swing moves every second step of the pattern later (step 4 is one of them); the knob is the pattern's
    turn(pg, "swing", -60)  # up
    swing = int(knob_text(pg, "swing").rstrip("%")) / 100
    assert 0.1 < swing <= 0.75
    wait_for(lambda: any(abs(n[1] - (0.75 + swing * 0.25)) < 0.02 for n in clip_notes(rig)))
    assert clip_notes(rig)[0][1] == 0.0 and pg.locator("#steps .st-pad.on").count() == 2  # still on its steps
    assert rig.state()["steps"]["swing"] == pytest.approx(swing)

    # Clear: the chosen sound; again within three seconds, the whole pattern
    pg.locator('#st-ov .st-row[data-pitch="38"]').click()
    pads.nth(4).click()
    wait_for(lambda: len(clip_notes(rig)) == 3)
    clear = pg.locator("#st-clear")
    assert clear.inner_text() == "Clear" and clear.bounding_box()["height"] >= 43.9
    clear.click()
    wait_for(lambda: [n[0] for n in clip_notes(rig)] == [KICK, KICK])  # the snare's row is empty
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 0")
    assert clear.inner_text() == "All"
    clear.click()
    wait_for(lambda: clip_notes(rig) == [])
    pg.wait_for_function("document.querySelectorAll('#st-ov .c.on').length === 0")
    assert clear.inner_text() == "Clear" and len(rig.track("Drums").arrangement_clips) == 1  # the clip stays, empty
    assert no_scroll(pg) and pg.errors == []


def test_a_pattern_of_two_bars_shows_a_bar_at_a_time(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    pads = pg.locator("#steps .st-pad")
    pads.nth(0).click()
    wait_for(lambda: len(clip_notes(rig)) == 1)
    assert pg.locator('#st-bars [data-v="1"]').get_attribute("aria-pressed") == "true"
    assert pg.locator("#st-view").count() == 0  # one bar: no bar to choose
    pg.locator('#st-bars [data-v="2"]').click()
    pg.wait_for_selector('#st-bars [data-v="2"].on')
    pg.wait_for_selector("#st-view")
    clip = rig.track("Drums").arrangement_clips[0]
    assert (clip.start_time, clip.end_time) == (0.0, 8.0) and clip_notes(rig) == [(KICK, 0.0, 0.25, 100)]
    pg.wait_for_selector('#steps .st-pad[data-k="0"].on')
    keys = pg.locator("#st-view button, #st-bars button")
    assert all(
        b["width"] >= 43.9 and b["height"] >= 43.9
        for b in keys.evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())")
    )
    # the second bar of the pattern: its own 16 steps, on the same pads
    pg.locator('#st-view [data-v="1"]').click()
    assert pg.locator("#st-barn").inner_text() == "Bar 2" and pg.locator("#steps .st-pad.on").count() == 0
    pads.nth(4).click()
    wait_for(lambda: clip_notes(rig) == [(KICK, 0.0, 0.25, 100), (KICK, 5.0, 0.25, 100)])
    wait_for(lambda: (rig.state()["steps"] or {}).get("view") == 1)
    focus = rig.state()["steps"]
    assert focus["bars"] == 2 and len(focus["steps"]) == 32 and focus["steps"][20] == 100
    assert no_scroll(pg)
    # the next pattern is two bars on
    pg.locator('#steps [data-st="bar"][data-by="1"]').click()
    pg.wait_for_function("document.querySelector('#st-barn').textContent === 'Bar 3'")
    # back, and to one bar again: the clip is one bar, the second bar's note is gone
    pg.locator('#steps [data-st="bar"][data-by="-1"]').click()
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 1")
    pg.locator('#st-bars [data-v="1"]').click()
    pg.wait_for_selector('#st-bars [data-v="1"].on')
    wait_for(lambda: clip_notes(rig) == [(KICK, 0.0, 0.25, 100)])
    assert (rig.track("Drums").arrangement_clips[0].end_time) == 4.0

    # four bars with another clip in the way: the bar says so, nothing is cut, and one bar is still there to go back to
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(8.0, 4.0)\nresult = 1")
    pg.locator('#st-bars [data-v="4"]').click()
    pg.wait_for_selector("#st-barn[data-blocked]")
    assert pg.locator("#steps .st-pad:disabled").count() == 16
    assert [(c.start_time, c.end_time) for c in rig.track("Drums").arrangement_clips] == [(0.0, 4.0), (8.0, 12.0)]
    pg.locator('#st-bars [data-v="1"]').click()
    pg.wait_for_selector("#st-barn:not([data-blocked])")
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 1")
    assert no_scroll(pg) and pg.errors == []


def test_history_has_a_row_for_each_change_and_undo_puts_the_notes_back(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    pads = pg.locator("#steps .st-pad")
    for k in (0, 4, 8):
        pads.nth(k).click()
    wait_for(lambda: len(notes(rig)) == 3)
    pg.wait_for_function("window.zpkt.S.hist.entries.length === 2")  # the new track, and the run of taps as one
    pg.locator("#khist").click()
    pg.wait_for_selector("#sheet.on .he")
    texts = pg.locator("#sheet .he .ht").all_inner_texts()
    assert texts[0].split("\n")[0].split() == ["Drums", "bar", "1", "·", "3", "changes"]
    assert "new track · 909 Core Kit" in texts[1] and "no undo: 1 track" in texts[1]
    assert no_scroll(pg)
    pg.locator("#hclose").click()

    pg.locator("#kundo").click()  # the whole run goes, and the clip it made; the pads follow
    wait_for(lambda: notes(rig) == [] and rig.track("Drums").arrangement_clips == ())
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 0")
    pg.locator("#kredo").click()
    wait_for(lambda: len(notes(rig)) == 3)
    pg.wait_for_function("document.querySelectorAll('#steps .st-pad.on').length === 3")

    # paint, then undo: the copies go
    pg.locator('#steps [data-st="paint"]').click()
    pg.wait_for_selector("#lanes .lane.paint .st-cell.p.src")
    box = pg.locator('#lanes .lane.paint .st-cell[data-bar="4"]').bounding_box()
    end = pg.locator('#lanes .lane.paint .st-cell[data-bar="7"]').bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + 10)
    pg.mouse.down()
    pg.mouse.move(end["x"] + end["width"] / 2, end["y"] + 10, steps=4)
    pg.mouse.up()
    wait_for(lambda: len(rig.track("Drums").arrangement_clips) == 5)
    pg.wait_for_function("window.zpkt.S.hist.entries.some(e => e.what === 'paint' && e.count === 4)")
    pg.locator("#kundo").click()
    wait_for(lambda: len(rig.track("Drums").arrangement_clips) == 1)
    pg.wait_for_function("document.querySelectorAll('#lanes .lane.paint .st-cell.p').length === 1")
    pg.locator("#khist").click()
    pg.wait_for_selector("#sheet.on .he.undone")
    assert "painted 4 clips" in pg.locator("#sheet .he.undone .ht").first.inner_text()
    assert pg.errors == []


def big_kit(rig, name="Big", sounds=16):
    """A MIDI track with a Drum Rack of `sounds` filled pads, put into the fake set directly."""
    from zpkt.live.testing import sets

    rig.conn.run(f"t = song.create_midi_track(0)\nt.name = {name!r}\nresult = 1")
    pads = [{"name": f"Sound {n + 1}", "note": 36 + n} for n in range(sounds)]
    rig.track(name)._add_device(sets.device({"device": "Drum Rack", "name": "Kit", "chains": pads}))


@pytest.mark.parametrize(
    "viewport", [{"width": 390, "height": 664}, PHONE, DESKTOP], ids=["short phone", "phone", "desktop"]
)
def test_a_kit_of_sixteen_sounds_shows_a_part_at_a_time_and_every_sound_is_a_step_away(browser, rig, viewport):
    big_kit(rig)
    pg = song(browser, rig, viewport)
    lane = pg.locator('#lanes .lane[data-name="Big"]')  # an empty MIDI track has a lane
    assert lane.locator(".rg").count() == 0
    lane.locator(".tr").click()
    assert pg.locator("#songnew").inner_text() == ""  # the set has a MIDI track: no key to make one
    pg.locator('#songsel [data-st="open"]').click()
    pg.wait_for_selector("#steps .st-pad:not([disabled])")
    shown = pg.locator("#st-ov .st-row:visible .n").all_inner_texts()
    assert 3 <= len(shown) <= 8 and shown == [f"Sound {n + 1}" for n in range(len(shown))]
    assert pg.locator("#st-ov .st-row").count() == 16 and pg.locator("#st-name").inner_text() == "Sound 1"
    heights = pg.locator("#st-ov .st-row:visible").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
    assert min(heights) >= 22 and no_scroll(pg)
    before, after = (
        pg.locator('#steps [data-st="snd"][data-by="-1"]'),
        pg.locator('#steps [data-st="snd"][data-by="1"]'),
    )
    assert before.is_disabled() and after.bounding_box()["height"] >= 43.9 and after.bounding_box()["width"] >= 43.9
    for _ in range(len(shown)):  # past the last row in view: the next part of the kit shows, with the chosen sound
        after.click()
    nth = len(shown) + 1
    assert pg.locator("#st-name").inner_text() == f"Sound {nth}"
    assert pg.locator("#st-ov .st-row:visible .n").first.inner_text() == f"Sound {nth}"
    assert pg.locator("#st-ov .st-row.sel:visible .n").inner_text() == f"Sound {nth}"
    pg.locator("#steps .st-pad").nth(2).click()
    wait_for(
        lambda: [(n.pitch, n.start_time) for c in rig.track("Big").arrangement_clips for n in c._notes]
        == [(36 + nth - 1, 0.5)]
    )
    for _ in range(16 - nth):
        after.click()
    assert pg.locator("#st-name").inner_text() == "Sound 16" and after.is_disabled()
    before.click()
    assert pg.locator("#st-name").inner_text() == "Sound 15"
    wait_for(lambda: (rig.state()["steps"] or {}).get("name") == "Sound 15")  # the focus follows the sound
    box = pg.locator("#steps .st-ml").bounding_box()
    assert box["y"] + box["height"] <= viewport["height"] and no_scroll(pg)
    assert pg.errors == []


def test_a_page_that_goes_away_with_steps_open_lets_the_focus_go(browser, rig):
    pg = song(browser, rig)
    make_drums(pg, rig)
    wait_for(lambda: rig.state()["steps"] is not None)
    pg.goto(rig.url + "/desk/")  # another document: the page with Steps is gone
    assert wait_for(lambda: rig.state()["steps"] is None)
