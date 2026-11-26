"""The proposal's card in the chat, and its row in History (WebKit, on FakeLive, a scripted agent): the person can
decide from the card alone on a phone, the card stays and says what came of it, and the History row says what undo
does not take back. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.test_ask_tab import FITS, chat, open_app, send, text
from tests.app.test_desk_touch import open_lead
from tests.app.test_live_change import KICK, VOL, names
from tests.app.test_live_propose import HATS, whole
from zpkt.app.ask.testing import Call
from zpkt.app.bus import Command
from zpkt.live import chain, newtrack

playwright_sync = pytest.importorskip("playwright.sync_api")

LONG_CODE = "\n".join(f"song.tempo = {90 + k}.0  # line {k} of a long routing change" for k in range(30))
assert 1200 < len(LONG_CODE) < 2000
BATCH = {
    "why": "Parallel drive on the hats",
    "steps": [
        {"set": VOL, "to": 0.5},
        {"remove": "desk Sat", "track": HATS},
        {"new_track": "audio", "name": "Parallel"},
        {"add": "Saturator", "track": "Parallel"},
        {"code": LONG_CODE, "does": "Sets the tempo, one line at a time."},
    ],
}
HALF = {
    "why": "Half of it",
    "steps": [
        {"remove": "desk Sat", "track": HATS},
        {"code": "raise ValueError('no such clip')", "does": "Breaks."},
        {"set": VOL, "to": 0.5},
    ],
}
NOT_NOW = {"why": "Not now", "steps": [{"remove": "desk Glue", "track": KICK}]}
EMOJI = r"/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    monkeypatch.setattr(newtrack.time, "sleep", lambda s: None)


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def test_the_card_can_be_decided_from_alone_on_a_phone_and_stays_to_say_what_happened(asked, browser):
    rig = asked.rig
    before = whole(rig)
    pg = open_app(browser, asked, path="/app/#ask")  # 375 x 812
    fr = chat(pg)
    asked.providers["claude"].script = [Call("propose_live", BATCH), text("All done.")]
    send(fr, "parallel drive please")
    card = fr.locator(".card.prop")
    card.wait_for()
    assert card.get_attribute("data-state") == "waiting"
    assert card.locator(".prop-why").inner_text() == "Parallel drive on the hats"
    lines = card.locator(".prop-steps li")
    texts = [t.strip() for t in lines.locator(".prop-text").all_inner_texts()]
    assert texts[0].startswith("Set Kick bus volume to ") and texts[1:] == [
        "Remove desk Sat from Hats bus",
        "New audio track: Parallel",
        "Add Saturator to Parallel",
        "Sets the tempo, one line at a time.",
    ]
    # what undo cannot take back is marked on its own line: an icon and two words
    marked = [lines.nth(k).locator(".prop-keep").count() for k in range(5)]
    assert marked == [0, 1, 1, 0, 1]
    keep = lines.nth(1).locator(".prop-keep")
    assert keep.inner_text().strip() == "No undo" and keep.locator("svg").count() == 1 and keep.is_visible()
    # the code is under its sentence, small and monospace, and scrolls inside itself
    code = lines.nth(4).locator("pre.prop-code")
    assert code.inner_text() == LONG_CODE and lines.locator("pre.prop-code").count() == 1
    box = code.evaluate(
        "n => { const s = getComputedStyle(n); return {h: n.clientHeight, sh: n.scrollHeight, w: n.clientWidth,"
        " sw: n.scrollWidth, oy: s.overflowY, ox: s.overflowX, font: s.fontFamily, size: parseFloat(s.fontSize)}; }"
    )
    assert box["h"] <= 140 < box["sh"] and box["sw"] > box["w"] and box["oy"] == "auto" and box["ox"] == "auto"
    assert "mono" in box["font"].lower() and box["size"] <= 13
    # two buttons with icons, big enough for a thumb, side by side
    buttons = card.locator(".perm-options button")
    assert [b.strip() for b in buttons.all_inner_texts()] == ["Do it", "Don't"]
    boxes = [buttons.nth(k).bounding_box() for k in range(2)]
    assert all(b["height"] >= 44 and b["width"] >= 120 for b in boxes) and boxes[0]["y"] == boxes[1]["y"]
    assert buttons.nth(0).locator("svg").count() == 1 and buttons.nth(1).locator("svg").count() == 1
    assert not card.evaluate(f"n => {EMOJI}.test(n.textContent)")
    # it fits the phone: nothing scrolls sideways, and the page itself does not scroll (the transcript does)
    assert pg.evaluate(FITS) and fr.locator("body").evaluate(f"() => {FITS}")
    assert fr.locator("#msgs").evaluate("m => m.scrollWidth <= m.clientWidth")
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight")
    assert fr.locator("body").evaluate("() => document.documentElement.scrollHeight <= innerHeight")
    whole_card = card.bounding_box()
    assert whole_card["x"] >= 0 and whole_card["x"] + whole_card["width"] <= 375
    assert whole(rig) == before and rig.desk.history.entries == []  # shown, and nothing has moved

    buttons.nth(0).click()
    fr.locator('.card.prop[data-state="done"]').wait_for()
    fr.locator("text=All done.").wait_for()
    assert card.locator(".prop-state").inner_text().strip() == "Done" and card.locator(".prop-state svg").count() == 1
    assert card.locator(".perm-options").is_hidden()
    assert lines.evaluate_all("ls => ls.map(l => l.dataset.step)") == ["done"] * 5
    assert lines.locator(".prop-n svg").count() == 5  # each step ticked
    assert "desk Sat" not in names(rig, HATS) and rig.live.song.tracks[-1].name == "Parallel"
    assert rig.live.song.tempo == 119.0 and rig.track(KICK).mixer_device.volume.value == 0.5

    pg.reload()  # the card is part of the transcript: it is there again, with what happened
    fr = chat(pg)
    again = fr.locator(".card.prop")
    again.wait_for()
    assert again.get_attribute("data-state") == "done" and again.locator(".perm-options").is_hidden()
    assert again.locator(".prop-state").inner_text().strip() == "Done"
    assert again.locator(".prop-steps li").count() == 5 and again.locator(".prop-keep").count() == 3
    assert pg.errors == [], pg.errors


def test_the_card_says_failed_at_a_step_and_not_done(asked, browser):
    rig = asked.rig
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    asked.providers["claude"].script = [Call("propose_live", HALF), Call("propose_live", NOT_NOW), text("So.")]
    send(fr, "two things")
    first = fr.locator(".card.prop").nth(0)
    first.wait_for()
    first.locator("button.do").click()
    fr.locator('.card.prop[data-state="failed"]').wait_for()
    said = " ".join(first.locator(".prop-state").inner_text().split())
    assert said.startswith("Failed at step 2") and "no such clip" in said
    assert first.locator(".prop-steps li").evaluate_all("ls => ls.map(l => l.dataset.step)") == [
        "done",
        "failed",
        "skipped",
    ]
    assert "desk Sat" not in names(rig, HATS) and rig.track(KICK).mixer_device.volume.value != 0.5
    second = fr.locator(".card.prop").nth(1)
    second.wait_for()
    assert second.get_attribute("data-state") == "waiting" and first.locator(".perm-options").is_hidden()
    second.locator("button.dont").click()
    fr.locator('.card.prop[data-state="declined"]').wait_for()
    fr.locator("text=So.").wait_for()
    assert second.locator(".prop-state").inner_text().strip() == "Not done"
    assert second.locator(".prop-steps li").evaluate_all("ls => ls.map(l => l.dataset.step)") == ["skipped"]
    assert "desk Glue" in names(rig, KICK)  # declined: still there
    assert fr.locator(".card.prop").count() == 2  # both stay in the transcript
    assert pg.errors == [], pg.errors


def test_the_history_row_says_what_undo_does_not_take_back(rig, browser):
    pg = open_lead(browser, rig)
    code, reply = rig.desk.bus.submit(Command("live.propose", "agent", BATCH, approval="user", group="ask-s1"))
    assert code == 200, reply
    pg.wait_for_function("document.querySelectorAll('#hrows .he.row').length === 1")
    row = pg.locator("#hrows .he.row")
    said = " ".join(row.inner_text().split())
    assert "Parallel drive on the hats" in said and "1 control, 1 device" in said
    assert "no undo: 1 removed, 1 track, 1 code" in said
    assert row.locator(".hv.nu svg").count() == 1 and row.locator(".who.agent").inner_text() == "agent"
    pg.locator("#kundo").click()
    pg.wait_for_function("document.querySelectorAll('#hrows .he.undone').length === 1")
    undone = pg.locator("#hrows .he.undone")
    assert undone.locator(".tagu").inner_text() == "undone in part"  # it does not say more than Undo did
    assert "no undo: 1 removed, 1 track, 1 code" in " ".join(undone.inner_text().split())
    assert "desk Sat" not in names(rig, HATS) and rig.live.song.tracks[-1].name == "Parallel"  # left as they are
    assert names(rig, "Parallel") == []  # the added device is taken back
    assert pg.errors == []  # type: ignore[attr-defined]
