"""The Ask page in WebKit, on the real server with a scripted agent.

It checks the page as one tab of the app: the shared tab bar (and the plain row of links without it), the one long
conversation with its older parts and earlier chats, the summary divider, page links drawn as cards, and the stub an
old control panel leaves. They need the playwright extra and its WebKit and skip when either is missing. The agent
is a scripted provider: no model. The shell's files (/app/shell/) are stood in for by small stubs.
"""

from __future__ import annotations

import pytest

from zpkt.app.ask.testing import Call, Permit

playwright_sync = pytest.importorskip("playwright.sync_api")

BLOCK = '```zpkt-surface\n{"title": "Kick: decay", "controls": [{"kind": "knob", "id": "decay", "label": "Decay", "min": 50, "max": 800, "value": 240, "unit": "ms", "midiSlot": 0}, {"kind": "ab", "id": "ab", "a": {"src": "renders/before.wav"}, "b": {"src": "renders/after.wav"}}]}\n```'
PAGE = {
    "title": "Kick: level",
    "groups": [{"name": "Level", "controls": [{"target": "Kick bus/volume", "role": "level"}]}],
}
# What the shell track serves at /app/shell/: the contract, as small as it can be.
NAV_JS = """
const nav = document.getElementById('tabs');
nav.innerHTML = ['desk', 'song', 'options'].map((t) => `<a data-t="${t}" href="/app/#${t}">${t}</a>`).join('')
  + '<a data-t="ask" class="on" aria-current="page" href="/app/ask/">ask</a>';
nav.dataset.at = matchMedia('(min-width:700px)').matches ? 'top' : 'bottom';
"""
SHELL_CSS = (
    "#tabs[data-at=top]{order:-1}#tabs>a{flex:1;height:52px;display:flex;align-items:center;justify-content:center}"
)
LISTEN_JS = "document.getElementById('listen').innerHTML = '<button id=\"listenBtn\">Listen</button>';"
STUBS = {
    "nav.js": ("text/javascript", NAV_JS),
    "shell.css": ("text/css", SHELL_CSS),
    "listen.js": ("text/javascript", LISTEN_JS),
}


def text(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


def turn(ask, sid: str, words: str, answer: str) -> None:
    """One finished turn written straight into the transcript."""
    ask.store.emit(sid, {"type": "prompt", "text": words, "engine": "claude", "mode": "plan"})
    ask.store.emit(sid, text(answer))
    ask.store.emit(sid, {"type": "result", "status": "success", "stats": {}})
    ask.store.emit(sid, {"type": "run_end", "engine": "claude", "code": 0})


def stub(ctype: str, body: str):
    def answer(route) -> None:
        route.fulfill(content_type=ctype, body=body)

    return answer


def open_page(browser, asked, shell: bool = True, width: int = 390, height: int = 844):
    pg = browser.new_context(viewport={"width": width, "height": height}).new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    if shell:
        for name, (ctype, body) in STUBS.items():
            pg.route(f"**/app/shell/{name}", stub(ctype, body))
    else:  # as if the shell's files were not there
        pg.route("**/app/shell/**", lambda route: route.abort())
    pg.goto(asked.rig.url + "/app/ask/")
    pg.wait_for_selector("#box")
    pg.wait_for_selector("#tabs a")
    return pg


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
def page(asked, browser):
    pg = open_page(browser, asked)
    yield pg
    assert pg.errors == [], pg.errors


def send(pg, words: str) -> None:
    pg.fill("#box textarea", words)
    pg.click("#send")


def box(pg, selector: str) -> dict:
    return pg.locator(selector).bounding_box()


# ---- one tab of the app ----------------------------------------------------------------------------------------------
def test_the_tab_bar_is_the_shells_and_sits_under_the_composer_on_a_phone(asked, page):
    assert page.locator("#tabs a").count() == 4
    assert page.locator("#tabs a.on").get_attribute("href") == "/app/ask/"
    assert [a.get_attribute("href") for a in page.locator("#tabs a").all()[:3]] == [
        "/app/#desk",
        "/app/#song",
        "/app/#options",
    ]
    assert not page.locator("#tabs").evaluate("n => n.classList.contains('fallback')")
    bar, tabs, top = box(page, "#bar"), box(page, "#tabs"), box(page, "#top")
    assert top["y"] < bar["y"] and bar["y"] + bar["height"] <= tabs["y"] + 1  # the composer is above the tab bar
    assert tabs["y"] + tabs["height"] <= 844 + 1 and tabs["height"] >= 44
    assert page.locator("#listenBtn").is_visible()  # the Listen button's place, in the header
    assert box(page, "#listen")["y"] < bar["y"]
    assert page.locator("#side, #new, #list, #libBtn, #midiBtn").count() == 0  # the old standalone app's chrome


def test_without_the_shells_files_there_is_a_plain_row_of_four_links(asked, browser):
    pg = open_page(browser, asked, shell=False)
    assert pg.locator("#tabs").evaluate("n => n.classList.contains('fallback')")
    assert [a.inner_text() for a in pg.locator("#tabs a").all()] == ["Desk", "Song", "Options", "Ask"]
    assert pg.locator("#tabs a").first.get_attribute("href") == "/app/#desk"
    assert pg.locator("#tabs a.on").inner_text() == "Ask"
    assert box(pg, "#tabs a.on")["height"] >= 44
    assert box(pg, "#bar")["y"] + box(pg, "#bar")["height"] <= box(pg, "#tabs")["y"] + 1
    asked.providers["claude"].script = [text("Still here.")]
    send(pg, "does it work alone")  # a missing shell or Listen file does not break the page
    pg.wait_for_selector("text=Still here.")
    assert pg.errors == [], pg.errors


@pytest.mark.parametrize("width", [375, 1100])
def test_it_fits_a_phone_and_a_desktop_with_no_sideways_scroll(asked, browser, width):
    main = asked.ask.main()
    turn(asked.ask, main["id"], "a long line " * 30, "A table:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n" + "word " * 200)
    pg = open_page(browser, asked, width=width, height=700)
    pg.wait_for_selector("text=A table:")
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth")
    assert pg.evaluate("document.querySelector('#msgs').scrollWidth <= document.querySelector('#msgs').clientWidth")
    tabs, bar = box(pg, "#tabs"), box(pg, "#bar")
    if width < 700:
        assert bar["y"] + bar["height"] <= tabs["y"] + 1
    else:
        assert tabs["y"] < box(pg, "#top")["y"]  # from 700 px up the shell puts the bar first
    for sel in ("#send", "#moreBtn", "#engine", "#mode"):
        b = box(pg, sel)
        assert b["width"] >= 44 and b["height"] >= 44, (sel, b)
    assert pg.errors == [], pg.errors


# ---- one long conversation -------------------------------------------------------------------------------------------
def test_the_page_opens_the_main_conversation_and_a_question_gets_its_answer(asked, page):
    asked.providers["claude"].script = [text("Here is a kick.\n\n"), text("Tell me what to change.")]
    page.wait_for_selector("#empty")
    assert page.locator("#engine").input_value() == "claude"
    assert page.locator("#title").inner_text() == "Ask"
    send(page, "make me a kick")
    page.wait_for_selector("text=Tell me what to change.")
    assert page.locator(".m.user .bubble").first.inner_text() == "make me a kick"
    assert page.locator("#empty").count() == 0
    asked.ask.wait_idle()
    main = asked.ask.main()
    assert [s["id"] for s in asked.ask.store.all_sessions()] == [main["id"]]  # no new session was made
    assert [e["text"] for e in asked.ask.store.replay(main["id"]) if e["type"] == "prompt"] == ["make me a kick"]
    other = open_page(page.context.browser, asked)  # a second device: the same conversation, with its history
    other.wait_for_selector("text=Tell me what to change.")
    assert other.locator(".m.user .bubble").first.inner_text() == "make me a kick"


def test_an_ask_first_question_is_answered_from_the_page(asked, page):
    asked.providers["claude"].script = [Permit("Edit notes.md"), text("Done after your yes.")]
    page.select_option("#mode", "ask")
    send(page, "edit my notes")
    page.wait_for_selector("[data-perm] button")
    assert "Edit notes.md" in page.locator("[data-perm]").inner_text()
    page.click('[data-perm] button[data-option="yes"]')
    page.wait_for_selector("text=Answered: yes")
    page.wait_for_selector("text=Done after your yes.")
    assert asked.providers["claude"].answers == ["yes"]


def test_only_the_latest_part_loads_and_the_top_brings_the_part_before(asked, browser):
    main = asked.ask.main()
    for n in range(1, 46):
        turn(asked.ask, main["id"], f"question {n}", f"answer {n}")
    pg = open_page(browser, asked)
    pg.wait_for_selector("text=answer 45")
    said = lambda: [b.inner_text() for b in pg.locator(".m.user .bubble").all()]  # noqa: E731
    assert said()[0] == "question 26" and len(said()) == 20
    assert pg.evaluate(
        "(() => { const m = document.querySelector('#msgs'); return m.scrollHeight - m.scrollTop - m.clientHeight < 4; })()"
    )
    pg.evaluate("document.querySelector('#msgs').scrollTop = 0")  # reaching the top fetches the turns before
    pg.wait_for_selector("text=answer 6")
    assert said()[0] == "question 6" and len(said()) == 40
    assert pg.evaluate("document.querySelector('#msgs').scrollTop") > 200  # the reader was not thrown to the top
    pg.click("#older")  # the same, as a button
    pg.wait_for_selector("text=answer 1")
    assert said()[0] == "question 1" and len(said()) == 45 and not pg.locator("#older").is_visible()
    asked.providers["claude"].script = [text("answer 46")]
    send(pg, "question 46")  # the stream still follows after older parts were drawn
    pg.wait_for_selector("text=answer 46")
    assert said()[-1] == "question 46" and len(said()) == 46
    assert pg.errors == [], pg.errors


def test_earlier_chats_are_behind_one_entry_and_read_only(asked, page):
    main = asked.ask.main()
    old = asked.ask.store.create("The old kick chat", main["workspace"], main["cwd"])
    turn(asked.ask, old["id"], "an old question", "an old answer")
    page.click("#moreBtn")
    page.wait_for_selector(".old")
    assert page.locator(".old").count() == 1 and "The old kick chat" in page.locator(".old").inner_text()
    page.click(".old")
    page.wait_for_selector("text=an old answer")
    assert page.locator("#title").inner_text() == "The old kick chat"
    assert not page.locator("#bar").is_visible() and page.locator("#robar").is_visible()
    assert page.locator("#tabs a").count() == 4  # the tabs stay
    page.click("#backBtn")
    page.wait_for_selector("#empty")
    assert page.locator("#bar").is_visible() and page.locator("#title").inner_text() == "Ask"
    assert asked.ask.store.replay(old["id"])[-1]["type"] == "run_end"  # nothing was added to it


# ---- the summary divider ---------------------------------------------------------------------------------------------
def test_a_compaction_draws_a_quiet_divider_that_opens_to_the_summary(asked, browser):
    main = asked.ask.main()
    sid = main["id"]
    turn(asked.ask, sid, "the first thing", "the first answer")
    asked.ask.store.emit(sid, {"type": "prompt", "text": "and now", "engine": "claude", "mode": "plan"})
    asked.ask.store.emit(sid, {"type": "compacting", "engine": "claude", "turns": 1, "tokens": 120000})
    asked.ask.store.emit(
        sid,
        {
            "type": "compacted",
            "engine": "claude",
            "summary": "## What the user wants\n\nA **harder** kick.",
            "keep_from": 4,
            "turns": 1,
            "tokens": 120000,
            "pages": [{"id": "kick-level", "title": "Kick: level", "link": "/app/#page=kick-level"}],
        },
    )
    asked.ask.store.emit(sid, text("Going on."))
    asked.ask.store.emit(sid, {"type": "run_end", "engine": "claude", "code": 0})
    pg = open_page(browser, asked)
    pg.wait_for_selector("text=Going on.")
    assert pg.locator("details.cmp").count() == 1 and pg.locator("text=Summarising the earlier").count() == 0
    assert pg.locator("details.cmp summary").inner_text().strip() == "Earlier conversation summarised"
    assert not pg.locator("details.cmp .bubble").is_visible()
    assert pg.locator("text=the first answer").is_visible()  # nothing is cut from what can be read
    pg.click("details.cmp summary")
    assert pg.locator("details.cmp .bubble strong").inner_text() == "harder"
    assert pg.locator("details.cmp a.pcard").get_attribute("href") == "/app/#page=kick-level"
    # live: the line that says it is summarising turns into the divider; a failed one says so
    asked.ask.store.emit(sid, {"type": "prompt", "text": "third", "engine": "claude", "mode": "plan"})
    asked.ask.store.emit(sid, {"type": "compacting", "engine": "claude", "turns": 2, "tokens": 130000})
    pg.wait_for_selector("text=Summarising the earlier conversation")
    asked.ask.store.emit(
        sid, {"type": "compacted", "engine": "claude", "summary": "", "failed": True, "error": "x", "pages": []}
    )
    pg.wait_for_selector("text=could not be summarised")
    assert pg.locator("text=Summarising the earlier conversation").count() == 0
    assert pg.errors == [], pg.errors


# ---- links, not widgets ----------------------------------------------------------------------------------------------
def test_a_link_to_a_page_draws_as_a_card_with_a_map_of_the_minilab(asked, page):
    gate = asked.ask.gate
    code, made = gate.call("s1", gate.token("s1"), "make_page", {"spec": PAGE})
    assert code == 200, made
    link = made["markdown"]
    asked.providers["claude"].script = [
        text(f"The kick's level is on a page.\n\n{link}\n\nAlso [a missing one](/app/#page=nope) "),
        text("and [the docs](https://example.com/docs) and [the desk](/app/#desk)."),
    ]
    send(page, "put the kick level on a fader")
    page.wait_for_selector("a.pcard svg")
    card = page.locator("a.pcard").first
    assert card.get_attribute("href") == made["link"] and card.get_attribute("target") is None
    assert card.locator("b").inner_text() == "Kick: level" and "Open on the Desk" in card.inner_text()
    lit, grey = card.locator("svg .on").count(), card.locator("svg .off").count()
    assert lit == 1 and lit + grey == 20  # every MiniLab control is shown; the mapped one is lit
    assert card.bounding_box()["height"] >= 44
    missing = page.locator('a.pcard[data-page="nope"]')  # no such page: the title and the link, no map
    assert missing.locator("b").inner_text() == "a missing one" and missing.locator("svg").count() == 0
    assert page.locator('a[href="https://example.com/docs"]').get_attribute("target") == "_blank"
    assert page.locator('.bubble a[href="/app/#desk"]:not(.pcard)').get_attribute("target") is None
    assert page.locator(".zs-card, .zs-slot").count() == 0


def test_an_old_control_panel_is_a_stub_and_its_rendered_files_still_play(asked, browser):
    main = asked.ask.main()
    sid = main["id"]
    asked.ask.store.emit(sid, {"type": "prompt", "text": "make me a kick", "engine": "claude", "mode": "plan"})
    asked.ask.store.emit(sid, text(f"Here is a kick.\n\n{BLOCK}\n\n```audio\nrenders/kick.wav\n```\n"))
    asked.ask.store.emit(sid, {"type": "surface", "spec": {"title": "Recalled", "controls": []}, "name": "My kick"})
    asked.ask.store.emit(sid, {"type": "run_end", "engine": "claude", "code": 0})
    pg = open_page(browser, asked)
    pg.wait_for_selector(".oldpanel")
    stubs = pg.locator(".oldpanel")
    assert stubs.count() == 2
    assert "An older control panel; ask for a page to use it again." in stubs.first.inner_text()
    assert (
        stubs.first.locator("b").inner_text() == "Kick: decay" and stubs.nth(1).locator("b").inner_text() == "My kick"
    )
    assert pg.locator(".zs-card, .zs-slot, .zs-w").count() == 0  # no live widget, nothing armed
    played = [a.get_attribute("src") for a in stubs.first.locator("audio").all()]
    assert len(played) == 2 and all(f"/sessions/{sid}/file?path=renders" in s for s in played)  # the A/B's two files
    assert pg.locator(".bubble > figure.aud audio").count() == 1  # an audio block is a player, as before
    assert pg.evaluate("typeof window.Zpkt.hydrate") == "undefined" and pg.evaluate(
        "!('requestMIDIAccess' in window.Zpkt)"
    )
    assert pg.errors == [], pg.errors


def test_a_tool_call_still_draws_in_the_work_view(asked, page):
    asked.providers["claude"].script = [text("First answer."), Call("read_state")]
    send(page, "hello there")
    page.wait_for_selector("text=First answer.")
    asked.ask.wait_idle()
    page.wait_for_selector(".wk-trace, .wk-step")
