"""The Song is the song in Live: one lane per track of the open set, its Arrangement clips as regions, the locators.
Read through the pager (arrangement.read), kept until Live says a clip or a locator changed. On FakeLive."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from zpkt.app import deskstate
from zpkt.app.bus import Command


def add_clip(rig, track: int, start: float, length: float, name: str = "") -> None:
    rig.conn.run(
        f"t = song.create_midi_track(-1) if {track} < 0 else song.tracks[{track}]\n"
        f"c = t.create_midi_clip({start!r}, {length!r})\nc.name = {name!r}\nresult = 1"
    )


def test_the_read_is_tracks_with_their_arrangement_clips_as_regions_in_beats(rig):
    code, got = rig.command("arrangement.read")
    assert code == 200 and got["ok"] and got["beats_per_bar"] == 4.0 and got["bars"] == 40
    names = [t["name"] for t in got["tracks"]]
    assert names == [
        t.name for t in rig.live.song.tracks if not t.name.startswith("mon ")
    ]  # the monitor's are not the song
    with_clips = [t for t in got["tracks"] if t["regions"]]
    assert with_clips
    region = with_clips[0]["regions"][0]
    assert set(region) == {"id", "start", "end", "name", "color", "muted"} and region["end"] > region["start"]
    assert region["id"] == f"{with_clips[0]['id']}@{region['start']:g}"  # holds while the region stays where it is
    ids = [r["id"] for t in got["tracks"] for r in t["regions"]]
    assert len(ids) == len(set(ids))
    assert rig.desk.bus.submit(Command("arrangement.read", "agent", {}))[0] == 200  # a read: an agent may


def test_it_is_kept_until_live_says_a_clip_changed_and_then_read_again(rig):
    rig.command("arrangement.read")
    calls = len(rig.live.calls)
    rig.command("arrangement.read")
    assert len(rig.live.calls) == calls  # kept: Live was not asked again
    q = rig.desk.subscribe(app=True)
    add_clip(rig, -1, 8.0, 8.0, "new idea")
    assert wait_for(lambda: any(m["t"] == "arr" for m in list(q.queue)))  # the pager says so; the page reads again
    got = rig.command("arrangement.read")[1]
    last = got["tracks"][-1]
    assert [(r["start"], r["end"], r["name"]) for r in last["regions"]] == [(8.0, 16.0, "new idea")]
    assert rig.command("arrangement.read", {"fresh": True})[0] == 200


def test_the_view_names_colours_and_counts_bars_from_the_last_clip():
    read = {
        "tracks": [
            {"i": 3, "name": "Kick", "color": 0xFF8800, "mute": True, "clips": [[16.0, 48.0, "drop", 0, False]]}
        ],
        "cues": [[0.0, "Build"], [16.0, "Drop"]],
        "length": 0.0,
    }
    view = deskstate.arrangement_view(read, "A set", 4.0)
    assert view["bars"] == 12 and view["set"] == "A set"
    track = view["tracks"][0]
    assert (track["id"], track["color"], track["muted"]) == ("t3", "#ff8800", True)
    assert track["regions"] == [
        {"id": "t3@16", "start": 16.0, "end": 48.0, "name": "drop", "color": "#ff8800", "muted": False}
    ]
    assert view["locators"] == [{"beat": 0.0, "name": "Build"}, {"beat": 16.0, "name": "Drop"}]
    assert deskstate.arrangement_view({}, "", 4.0) == {
        "set": "",
        "beats_per_bar": 4.0,
        "bars": 0,
        "tracks": [],
        "locators": [],
    }


playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def test_the_song_tab_shows_lives_tracks_and_regions_under_the_ruler(browser, rig):
    from zpkt.live.testing.lom import CuePoint

    song = rig.live.song
    song._cue_points += [CuePoint(0.0, "Build", parent=song), CuePoint(64.0, "Drop", parent=song)]
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#lanes .lane .rg")
    got = rig.command("arrangement.read")[1]
    drawn = [t for t in got["tracks"] if t["regions"]]  # a track with no regions has no lane
    assert 0 < len(drawn) < len(got["tracks"])
    assert pg.locator("#lanes .lane .ln").all_inner_texts() == [t["name"] for t in drawn]
    # the tempo and the time signature, by the ruler
    pg.wait_for_function("document.querySelector('#songtempo').textContent === '160 · 4/4'")
    assert pg.locator("#songtempo").is_visible()
    assert pg.locator("#lanes .rg").count() == sum(len(t["regions"]) for t in got["tracks"])
    first = next(t for t in got["tracks"] if t["regions"])
    region = pg.locator(f'#lanes .rg[data-region="{first["regions"][0]["id"]}"]')  # a region is its own element
    ruler, box = pg.locator("#ruler .rt").bounding_box(), region.bounding_box()
    beats = 40 * 4
    assert box["x"] == pytest.approx(ruler["x"] + ruler["width"] * first["regions"][0]["start"] / beats, abs=2)
    assert box["width"] == pytest.approx(
        ruler["width"] * (first["regions"][0]["end"] - first["regions"][0]["start"]) / beats, abs=3
    )
    assert pg.locator("#ruler .sec").all_inner_texts() == ["Build", "Drop"]  # the locators, as spans with their names
    numbers = pg.locator("#ruler .rt > .bn").all_inner_texts()
    assert numbers[0] == "1" and "17" in numbers
    rig.send({"t": "loop", "loop": "drop", "start": 64.0, "length": 96.0})
    pg.wait_for_selector("#songlp")
    assert "17–40" in pg.locator("#songloop").inner_text()
    rig.send({"t": "pos", "b": 80.0, "p": True})
    pg.wait_for_function("!document.querySelector('#songhead').hidden")
    head = pg.locator("#songhead").bounding_box()
    assert head["x"] + head["width"] / 2 == pytest.approx(ruler["x"] + ruler["width"] * 0.5, abs=2)
    # no controls on the lanes; with no MIDI track in the set, the one key that makes a drum track
    assert pg.locator("#song button:visible:not(#songtempo)").evaluate_all("els => els.map(e => e.dataset.st)") == [
        "pick"
    ]
    assert pg.locator("#song select, #song input").count() == 0
    add_clip(rig, -1, 8.0, 8.0, "new idea")  # a clip made in Live shows without a reload
    pg.wait_for_function("[...document.querySelectorAll('#lanes .rg')].some(e => e.textContent === 'new idea')")
    assert pg.locator("#lanes .lane").count() == len(drawn) + 1  # its track has a region now, so it has a lane
    rig.send({"t": "pos", "b": 80.0, "p": True, "bpm": 127.5})  # the tempo follows Live
    pg.wait_for_function("document.querySelector('#songtempo').textContent === '127.5 · 4/4'")
    assert errors == []


def test_a_tap_on_a_lane_chooses_the_track_and_its_solo_and_mute_keys_work_on_a_phone(browser, rig):
    """The cold-user walk, 26 November 2026: on the phone the Song had no way to mute a track. A tap on a lane chooses
    its track; the strip under the lanes names it and has Solo and Mute keys a finger hits. Nothing scrolls."""
    pg = browser.new_page(viewport={"width": 375, "height": 812})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#lanes .lane .rg")
    assert pg.locator("#songsel").is_hidden()  # no track chosen: no strip
    lane = pg.locator("#lanes .lane").first
    name = lane.get_attribute("data-name")
    track = next(t for t in rig.live.song.tracks if t.name == name)
    lane.locator(".tr").click()  # anywhere on the lane
    pg.wait_for_selector("#songsel [data-songflag]")
    assert "sel" in lane.get_attribute("class") and pg.locator("#songsel .sn").inner_text() == name
    for flag in ("solo", "mute"):
        key = pg.locator(f'#songsel [data-songflag="{flag}"]')
        box = key.bounding_box()
        assert box["height"] >= 43.9 and box["width"] >= 43.9
        key.click()
        wait_for(lambda flag=flag: getattr(track, flag) is True)
        pg.wait_for_selector(f'#songsel [data-songflag="{flag}"][aria-pressed="true"]')
        pg.wait_for_selector(f"#flags .chip.{flag}")  # the play bar says it too
        pg.locator(f'#songsel [data-songflag="{flag}"]').click()
        wait_for(lambda flag=flag: getattr(track, flag) is False)
        pg.wait_for_selector(f'#songsel [data-songflag="{flag}"][aria-pressed="false"]')
    pg.locator('#songsel [data-songflag="mute"]').click()
    pg.wait_for_selector("#lanes .lane.sel.muted")  # the lane shows it
    pg.locator('#songsel [data-songflag="mute"]').click()
    pg.wait_for_selector("#lanes .lane.sel:not(.muted)")
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight")  # still no scrolling
    lane.locator(".tr").click()  # a second tap lets the track go
    pg.wait_for_function("document.querySelector('#songsel').innerHTML === ''")
    assert errors == []


def test_a_tap_on_the_tempo_sets_it(browser, rig):
    """The tempo in the ruler is a key: it opens the Tempo sheet, and Set changes Live's tempo (the persona
    walkthrough, 27 November 2026: "No way to set tempo or key on the Song tab")."""
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_function(
        "document.querySelector('#songtempo') && document.querySelector('#songtempo').textContent === '160 · 4/4'"
    )
    pg.click("#songtempo")
    pg.wait_for_selector("#sheet.on #tempoin")
    assert pg.input_value("#tempoin") == "160"
    pg.fill("#tempoin", "123")
    pg.click("#tempoform button[type=submit]")
    pg.wait_for_function("!document.querySelector('#sheet.on')")
    assert rig.live.song.tempo == 123
    pg.close()
