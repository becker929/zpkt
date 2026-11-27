"""Abilities on the phone (WebKit, 375 x 812, a scripted agent on FakeLive): the card with "Always" and what it says
it kept, and the list in the Ask sheet with its Remove key. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.test_abilities import BPM, DOUBLE, SET_TEMPO, batch, keep
from tests.app.test_ask_tab import FITS, chat, open_app, send, text
from zpkt.app.ask.testing import Call
from zpkt.live import chain, newtrack

playwright_sync = pytest.importorskip("playwright.sync_api")
EMOJI = r"/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u"
NO_PAGE_SCROLL = "document.documentElement.scrollHeight <= innerHeight && document.body.scrollHeight <= innerHeight"
BROADER = {
    **SET_TEMPO,
    "code": "song.tempo = args['bpm'] * args['times']\nresult = {'tempo': args['bpm'] * args['times']}",
    "params": {**BPM, "times": {"type": "integer", "description": "how many times the number", "default": 1}},
    "args": {"bpm": 91.0},
}
HALVE = {
    "code": "r = use('set_tempo', {'bpm': args['bpm'] / 2})\nresult = {'halved_to': r['tempo']}",
    "does": "Sets the tempo to half a number.",
    "name": "halve_tempo",
    "params": BPM,
    "args": {"bpm": 180.0},
}


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


def test_the_card_offers_always_and_says_what_it_kept(asked, browser):
    rig = asked.rig
    keep(rig, SET_TEMPO)
    keep(rig, DOUBLE)  # it uses set_tempo: the card of a replacement says so
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    asked.providers["claude"].script = [
        Call("propose_live", batch(BROADER, HALVE, {"set": "Kick bus/volume", "to": 0.5}, why="Tempo by halves")),
        text("Kept."),
    ]
    send(fr, "tempo tools please")
    card = fr.locator(".card.prop")
    card.wait_for()
    lines = card.locator(".prop-steps li")
    # a code step: its sentence, then the name it would be kept as with this run's values, then the code
    assert lines.nth(0).locator(".prop-text").inner_text().strip() == "Sets the tempo."
    assert lines.nth(0).locator(".prop-sig").inner_text().strip() == "set_tempo(bpm = 91, times = 1)"
    assert lines.nth(1).locator(".prop-sig").inner_text().strip() == "halve_tempo(bpm = 180)"
    assert lines.nth(2).locator(".prop-sig, .prop-more, .prop-code").count() == 0  # an ordinary step has none
    replaces = " ".join(lines.nth(0).locator(".prop-rep").inner_text().split())
    assert replaces == "Replaces set_tempo, used by 1 ability" and lines.nth(0).locator(".prop-rep svg").count() == 1
    assert lines.nth(1).locator(".prop-rep").count() == 0
    assert lines.nth(1).locator(".chip").all_inner_texts() == ["set_tempo"]  # what it uses, as a chip
    assert lines.nth(1).locator(".prop-more > *").all_inner_texts() == ["uses", "set_tempo"]
    order = lines.nth(0).evaluate(
        "li => [...li.children].map(c => c.className.split(' ')[0]).filter(c => c.startsWith('prop-'))"
    )
    assert order == ["prop-n", "prop-text", "prop-keep", "prop-sig", "prop-more", "prop-code"]
    # three buttons, side by side, each a thumb's size, each with an icon
    buttons = card.locator(".perm-options button")
    assert [b.strip() for b in buttons.all_inner_texts()] == ["Do it", "Always", "Don't"]
    boxes = [buttons.nth(k).bounding_box() for k in range(3)]
    assert all(b["height"] >= 44 and b["width"] >= 88 for b in boxes) and len({b["y"] for b in boxes}) == 1
    assert boxes[0]["x"] < boxes[1]["x"] < boxes[2]["x"] and boxes[2]["x"] + boxes[2]["width"] <= 375
    assert all(buttons.nth(k).locator("svg").count() == 1 for k in range(3))
    assert all(buttons.nth(k).evaluate("b => b.scrollWidth <= b.clientWidth") for k in range(3))  # no label is cut
    assert not card.evaluate(f"n => {EMOJI}.test(n.textContent)")
    assert pg.evaluate(FITS) and fr.locator("body").evaluate(f"() => {FITS}")
    assert pg.evaluate(NO_PAGE_SCROLL) and fr.locator("body").evaluate(f"() => {NO_PAGE_SCROLL}")
    assert rig.desk.abilities.names() == ["double_tempo", "set_tempo"] and rig.live.song.tempo == 100.0

    card.locator("button.always").click()
    fr.locator('.card.prop[data-state="done"]').wait_for()
    fr.locator("text=Kept.").wait_for()
    said = " ".join(card.locator(".prop-state").inner_text().split())
    assert said == "Done Kept as abilities: set_tempo, halve_tempo"
    assert card.locator(".perm-options").is_hidden() and rig.live.song.tempo == 90.0
    assert rig.desk.abilities.names() == ["double_tempo", "halve_tempo", "set_tempo"]
    assert rig.desk.abilities.get("set_tempo")["code"] == BROADER["code"]
    pg.reload()
    fr = chat(pg)
    again = fr.locator(".card.prop")
    again.wait_for()
    assert (
        " ".join(again.locator(".prop-state").inner_text().split()) == "Done Kept as abilities: set_tempo, halve_tempo"
    )
    assert pg.errors == [], pg.errors


def test_a_proposal_with_no_code_keeps_two_buttons(asked, browser):
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    asked.providers["claude"].script = [Call("propose_live", batch({"remove": "desk Sat", "track": "Hats bus"}))]
    send(fr, "less sat")
    card = fr.locator(".card.prop")
    card.wait_for()
    assert [b.strip() for b in card.locator(".perm-options button").all_inner_texts()] == ["Do it", "Don't"]
    card.locator("button.dont").click()
    fr.locator('.card.prop[data-state="declined"]').wait_for()
    assert pg.errors == [], pg.errors


def test_the_sheet_lists_the_abilities_and_remove_takes_one_away_at_once(asked, browser):
    rig = asked.rig
    keep(rig, {**SET_TEMPO, "params": {"bpm": {**BPM["bpm"], "default": 120}}})
    keep(rig, DOUBLE)
    long_code = "\n".join(f"x{k} = {k}  # a line of an ability that is longer than its box" for k in range(30))
    keep(rig, {"code": long_code + "\nresult = 1", "does": "Counts.", "name": "count_up"})
    rig.desk.bus.submit(__import__("zpkt.app.bus", fromlist=["Command"]).Command(
        "ability.run", "agent", {"name": "set_tempo", "args": {"bpm": 99}}))  # fmt: skip
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    fr.locator("#moreBtn").click()
    fr.locator("#abList .ab").nth(2).wait_for()
    assert fr.locator(".ab-head h3").inner_text() == "Abilities" and fr.locator("#abCount").inner_text() == "3 of 50"
    rows = fr.locator("#abList .ab")
    assert rows.evaluate_all("rs => rs.map(r => r.dataset.ab)") == ["count_up", "double_tempo", "set_tempo"]
    one = fr.locator('#abList .ab[data-ab="set_tempo"]')
    assert one.locator("summary b").inner_text() == "set_tempo"
    assert one.locator(".ab-does").inner_text() == "Sets the tempo."
    assert one.locator(".ab-par").all_inner_texts() == ["bpm (number, default 120): the tempo, in BPM"]
    assert one.locator(".ab-meta > *").all_inner_texts() == ["1 run", "used by", "double_tempo"]
    two = fr.locator('#abList .ab[data-ab="double_tempo"]')
    assert two.locator(".ab-meta > *").all_inner_texts() == ["0 runs", "uses", "set_tempo"]
    # the code is behind the row: closed, then a box that scrolls inside itself
    code = fr.locator('#abList .ab[data-ab="count_up"] pre')
    assert code.is_hidden()
    fr.locator('#abList .ab[data-ab="count_up"] summary').click()
    assert code.is_visible() and code.inner_text().startswith("x0 = 0")
    box = code.evaluate("n => ({h: n.clientHeight, sh: n.scrollHeight, o: getComputedStyle(n).overflowY})")
    assert box["h"] <= 140 < box["sh"] and box["o"] == "auto"
    # the Remove key: an icon, a name for a screen reader, a thumb's size
    rm = one.locator(".ab-rm")
    size = rm.bounding_box()
    assert size["width"] >= 44 and size["height"] >= 44 and rm.locator("svg").count() == 1
    assert rm.get_attribute("aria-label") == "Remove set_tempo" and rm.inner_text().strip() == ""
    # nothing scrolls but the sheet itself, and it stays on the phone
    sheet = fr.locator("#moreSheet > div")
    fits = sheet.evaluate("n => { const r = n.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth"
                          " && r.top >= 0 && r.bottom <= innerHeight && n.scrollWidth <= n.clientWidth"
                          " && getComputedStyle(n).overflowY === 'auto'; }")  # fmt: skip
    assert fits and pg.evaluate(NO_PAGE_SCROLL) and fr.locator("body").evaluate(f"() => {NO_PAGE_SCROLL}")
    assert fr.locator("body").evaluate(f"() => {FITS}") and not sheet.evaluate(f"n => {EMOJI}.test(n.textContent)")

    rm.scroll_into_view_if_needed()
    rm.click()
    fr.locator('#abList .ab[data-ab="set_tempo"]').wait_for(state="detached")
    assert rig.desk.abilities.names() == ["count_up", "double_tempo"]  # gone at once
    assert fr.locator("#abCount").inner_text() == "2 of 50"
    broken = [" ".join(t.split()) for t in two.locator(".ab-meta > *").all_inner_texts()]
    assert broken == ["Broken: needs set_tempo", "0 runs", "uses", "set_tempo"]
    assert two.locator(".ab-meta .bad svg").count() == 1
    gate = asked.ask.gate
    code_, reply = gate.call("s1", gate.token("s1"), "ability_set_tempo", {"bpm": 100})
    assert code_ == 404 and "propose its code again" in reply["error"]
    assert pg.errors == [], pg.errors
