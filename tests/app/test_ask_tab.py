"""Ask as a tab inside /app/, in WebKit, on the real server with a scripted agent and a made-up Listen capture.

The chat is the page /app/ask/ in a frame that /app/ keeps: the Hear bar and Listen stay while I chat, an answer goes
on arriving while the Desk shows (the tab gets a mark), and a page link in the chat opens the page on the Desk with
no reload. They need the playwright extra and its WebKit and skip when either is missing. No model, no Live.
"""

from __future__ import annotations

import threading

import pytest

from tests.app.test_listen import listening  # noqa: F401  (the fixture)
from zpkt.app.ask.testing import Hold

playwright_sync = pytest.importorskip("playwright.sync_api")

PAGE = {
    "title": "Kick: level",
    "groups": [{"name": "Level", "controls": [{"target": "Kick bus/volume", "role": "level"}]}],
}
FITS = "document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth"


def text(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def open_app(browser, asked, path: str = "/app/", width: int = 375, height: int = 812):
    pg = browser.new_context(viewport={"width": width, "height": height}).new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(asked.rig.url + path)
    pg.wait_for_selector("#kplay")  # the first state has come
    return pg


def chat(pg):
    """The chat's frame, once its composer is there."""
    fr = pg.frame_locator("#ask iframe")
    fr.locator("#box").wait_for()
    return fr


def said(pg, words: str) -> None:
    """Wait until the chat holds these words, shown or not."""
    pg.wait_for_function(
        "w => document.querySelector('#ask iframe').contentDocument.querySelector('#thread').textContent.includes(w)",
        arg=words,
    )


def send(fr, words: str) -> None:
    fr.locator("#in").fill(words)
    fr.locator("#send").click()


def test_the_ask_tab_shows_the_chat_with_the_hear_bar_still_there(asked, browser):
    pg = open_app(browser, asked)
    assert pg.locator("#ask iframe").count() == 0  # the chat is made on first use
    pg.click("#tabs [data-t=ask]")
    fr = chat(pg)
    assert pg.evaluate("location.hash") == "#ask" and pg.evaluate("location.pathname") == "/app/"
    assert pg.locator("#tabs .on").get_attribute("data-t") == "ask"
    assert pg.locator("#kplay").is_visible() and pg.locator("#setname").is_visible()  # transport and identity
    assert pg.locator("#desk").is_hidden() and pg.locator("#ask").is_visible()
    # the chat has no tab bar, title or Listen button of its own: the app's are the only ones
    assert fr.locator("#tabs, #listen").count() == 0 and fr.locator("#top").is_hidden()
    assert fr.locator("#moreBtn").is_visible() and fr.locator("#moreBtn").bounding_box()["height"] >= 30
    asked.providers["claude"].script = [text("Here is a thought.")]
    send(fr, "what next")
    fr.locator("text=Here is a thought.").wait_for()
    assert pg.locator("#task").get_attribute("data-mark") is None  # nothing to flag: Ask is showing
    pg.click("#tabs [data-t=desk]")
    assert pg.locator("#desk").is_visible() and pg.locator("#ask").is_hidden()
    pg.click("#tabs [data-t=ask]")
    assert pg.locator("#ask iframe").count() == 1 and fr.locator("text=Here is a thought.").is_visible()
    assert pg.errors == [], pg.errors


def test_the_old_address_lands_on_the_ask_tab(asked, browser):
    pg = browser.new_page(viewport={"width": 375, "height": 812})
    pg.goto(asked.rig.url + "/app/ask/")
    pg.wait_for_url("**/app/#ask")
    pg.wait_for_selector("#kplay")
    chat(pg).locator("#in").wait_for()
    assert pg.locator("#tabs .on").get_attribute("data-t") == "ask"
    bare = browser.new_page(viewport={"width": 375, "height": 812})
    bare.goto(asked.rig.url + "/app/ask/?bare=1")  # the page alone, for tests and as a fallback
    bare.wait_for_selector("#box")
    assert bare.evaluate("location.pathname") == "/app/ask/" and bare.locator("#tabs > *").count() == 4
    assert bare.locator("#tabs [data-t=ask]").get_attribute("href") == "/app/#ask"


def test_listen_stays_on_from_the_desk_to_ask_and_back(asked, listening, browser):  # noqa: F811
    pg = open_app(browser, asked)
    pg.wait_for_selector("#listen button[data-state=off]")
    pg.click("#listen button")
    pg.wait_for_selector("#listen button[data-state=on]")
    pg.wait_for_function("zpktListen.stats.bytes > 48000")
    pg.evaluate("window.kept = 1")
    pg.click("#tabs [data-t=ask]")
    fr = chat(pg)
    assert (
        pg.locator("#listen button").get_attribute("data-state") == "on" and pg.locator("#listen button").is_visible()
    )
    before = pg.evaluate("zpktListen.stats.bytes")
    pg.wait_for_function("b => zpktListen.stats.bytes > b + 48000", arg=before)  # sound goes on arriving while I chat
    fr.locator("#in").fill("still playing?")
    pg.click("#tabs [data-t=desk]")
    assert pg.locator("#listen button").get_attribute("data-state") == "on"
    assert len(listening.source.streams) == 1 and listening.status()["listeners"] == 1  # one stream, never reopened
    assert pg.evaluate("window.kept") == 1 and pg.errors == [], pg.errors


def test_an_answer_keeps_arriving_while_the_desk_shows_and_the_tab_is_marked(asked, browser):
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    go = threading.Event()
    asked.providers["claude"].script = [text("The first part. "), Hold(go), text("And the second part.")]
    send(fr, "take your time")
    fr.locator("text=The first part.").wait_for()
    pg.click("#tabs [data-t=desk]")
    assert pg.locator("#ask").is_hidden() and pg.locator("#desk").is_visible()
    pg.wait_for_selector("#task[data-mark=busy]")
    go.set()
    said(pg, "And the second part.")  # it arrived in the chat while the Desk was showing
    pg.wait_for_selector("#task[data-mark=new]")
    dot = pg.evaluate("(() => { const s = getComputedStyle(document.querySelector('#task'), '::after');"
                      " return [parseFloat(s.width), s.backgroundColor]; })()")  # fmt: skip
    assert dot[0] >= 8 and dot[1] not in ("rgba(0, 0, 0, 0)", "transparent"), dot
    assert pg.locator("#task").get_attribute("aria-label") == "Ask, new answer"
    pg.click("#tabs [data-t=ask]")
    assert pg.locator("#task").get_attribute("data-mark") is None  # seen
    assert fr.locator("text=And the second part.").is_visible()
    assert pg.errors == [], pg.errors


def test_a_page_link_in_the_chat_opens_the_page_on_the_desk_with_no_reload(asked, browser):
    gate = asked.ask.gate
    code, made = gate.call("s1", gate.token("s1"), "make_page", {"spec": PAGE})
    assert code == 200, made
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    asked.providers["claude"].script = [text(f"On a page.\n\n{made['markdown']}\n\nOr [the song](/app/#song).")]
    send(fr, "kick level please")
    fr.locator("a.pcard").wait_for()
    pg.evaluate("window.kept = 42")
    fr.locator("a.pcard").click()
    pg.wait_for_function("document.querySelector('#pagename')?.textContent === 'Kick: level'")
    assert pg.locator("#desk").is_visible() and pg.locator("#ask").is_hidden()
    assert pg.locator("#tabs .on").get_attribute("data-t") == "desk"
    assert pg.evaluate("window.kept") == 42  # the same document: nothing was loaded again
    assert pg.evaluate("location.pathname") == "/app/"
    pg.click("#tabs [data-t=ask]")
    assert fr.locator("a.pcard").is_visible()  # and the same chat
    fr.locator('.bubble a[href="/app/#song"]').click()
    pg.wait_for_function("location.hash === '#song'")
    assert pg.locator("#song").is_visible() and pg.evaluate("window.kept") == 42
    assert pg.errors == [], pg.errors


def test_the_empty_chat_is_examples_that_fill_the_composer(asked, browser):
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    fr.locator("#empty .eg").first.wait_for()
    chips = fr.locator("#empty .eg").all()
    assert 3 <= len(chips) <= 4
    assert fr.locator("#empty").inner_text().split() == " ".join(c.inner_text() for c in chips).split()  # nothing else
    assert all(c.bounding_box()["height"] >= 44 for c in chips)
    words = chips[1].inner_text()
    chips[1].click()
    assert fr.locator("#in").input_value() == words
    assert fr.locator("#in").evaluate("n => document.activeElement === n")
    assert asked.providers["claude"].seen == []  # filling is not sending
    asked.providers["claude"].script = [text("Start with the low end.")]
    fr.locator("#send").click()
    fr.locator("text=Start with the low end.").wait_for()
    assert fr.locator("#empty").count() == 0
    assert (
        asked.providers["claude"].seen[-1].prompt.endswith(words) or words in asked.providers["claude"].seen[-1].prompt
    )


def test_the_cost_has_a_name(asked, browser):
    main = asked.ask.main()
    asked.ask.store.emit(main["id"], {"type": "prompt", "text": "hello", "engine": "claude", "mode": "build"})
    asked.ask.store.emit(main["id"], text("Hi."))
    asked.ask.store.emit(
        main["id"], {"type": "result", "status": "success", "stats": {"duration_ms": 4200}, "cost_usd": 0.2612}
    )
    asked.ask.store.emit(main["id"], {"type": "run_end", "engine": "claude", "code": 0})
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    cost = fr.locator(".stats .cost")
    cost.wait_for()
    assert cost.get_attribute("title") == "Cost" and cost.locator("svg").count() == 1
    assert cost.text_content() == "Cost $0.261"  # what a screen reader says; the eye gets the tag and the amount
    assert fr.locator(".stats .took").text_content() == "Time 4.2 s"


def test_a_phone_does_not_zoom_into_a_text_field(asked, browser):
    """A phone's browser zooms the page into a focused field whose type is under 16 px, and the cursor jumps while it
    does (Anthony, 26 November 2026, on the dense composer's 12 px box). Every field a person types in has 16 px
    type, and both documents ask for no zoom on focus."""
    pg = open_app(browser, asked, path="/app/#ask")
    fr = chat(pg)
    size = "e => parseFloat(getComputedStyle(e).fontSize)"
    assert fr.locator("#in").evaluate(size) >= 16
    box = fr.locator("#in").bounding_box()
    assert 30 <= box["height"] <= 34, box  # and the dense row is no taller for it
    fr.locator("#in").fill("one line of words")
    assert fr.locator("#in").evaluate("e => e.scrollHeight <= e.clientHeight + 1")  # a line fits without scrolling
    view = "() => document.querySelector('meta[name=viewport]').content"
    assert "maximum-scale=1" in pg.evaluate(view) and "maximum-scale=1" in fr.locator("body").evaluate(view)
    pg.goto(asked.rig.url + "/app/#desk")
    pg.wait_for_selector("#kplay")
    sizes = pg.evaluate(
        """() => { const out = {};
          for (const sel of ['.orgrow input', '.cpf input', '.mc .vt']) {
            const host = document.createElement('div'); host.className = sel.split(' ')[0].slice(1);
            const f = document.createElement('input'); if (sel.endsWith('.vt')) f.className = 'vt';
            host.append(f); document.body.append(host);
            out[sel] = parseFloat(getComputedStyle(f).fontSize); host.remove(); }
          return out; }"""
    )
    assert all(v >= 16 for v in sizes.values()), sizes


@pytest.mark.parametrize(("width", "height"), [(375, 812), (1200, 800), (375, 460)])
def test_it_fits_with_the_composer_above_the_tab_bar(asked, browser, width, height):
    main = asked.ask.main()
    asked.ask.store.emit(
        main["id"], {"type": "prompt", "text": "a long line " * 30, "engine": "claude", "mode": "build"}
    )
    asked.ask.store.emit(main["id"], text("A table:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n" + "word " * 300))
    asked.ask.store.emit(main["id"], {"type": "run_end", "engine": "claude", "code": 0})
    pg = open_app(browser, asked, path="/app/#ask", width=width, height=height)
    fr = chat(pg)
    fr.locator("text=A table:").wait_for()
    assert pg.evaluate(FITS) and fr.locator("body").evaluate(f"() => {FITS}")
    assert fr.locator("#msgs").evaluate("m => m.scrollWidth <= m.clientWidth")
    frame, tabs = pg.locator("#ask iframe").bounding_box(), pg.locator("#tabs").bounding_box()
    box, msgs = fr.locator("#box").bounding_box(), fr.locator("#msgs").bounding_box()  # in the app's coordinates
    assert box["y"] >= 0 and box["y"] + box["height"] <= height
    assert frame["x"] >= 0 and frame["x"] + frame["width"] <= width + 0.5
    assert pg.locator("#kplay").is_visible() and pg.locator("#listen").count() == 1  # the Hear bar is still there
    for sel in ("#send", "#moreBtn", "#engine"):  # the dense composer (dense.css): one row of low keys
        b = fr.locator(sel).bounding_box()
        assert b["width"] >= 28 and b["height"] >= 30, sel
    if width < 700:
        assert box["y"] + box["height"] <= tabs["y"] + 1  # the composer is above the tab bar
        assert tabs["y"] + tabs["height"] <= height + 1
        short = pg.evaluate("document.querySelector('#app').classList.contains('short')")
        assert short == (height < 600)
        assert msgs["height"] >= (120 if short else 250), msgs  # room to read
        assert pg.locator("#setname").is_visible()  # even compact, the Hear bar says which set
    else:
        assert tabs["y"] < 10 and msgs["height"] >= 300
    assert pg.errors == [], pg.errors
