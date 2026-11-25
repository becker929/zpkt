"""The Ask page in WebKit, on the real server with a scripted agent: ask, see the answer and a card, answer a question.

They need the playwright extra and its WebKit and skip when either is missing. The agent is a scripted provider: no
model. The page is Zpkt web's page code under /app/ask/, so this also checks that the changed paths all work.
"""

from __future__ import annotations

import pytest

from zpkt.app.ask.testing import Call, Permit

playwright_sync = pytest.importorskip("playwright.sync_api")

BLOCK = '```zpkt-surface\n{"title": "Kick: decay", "controls": [{"kind": "knob", "id": "decay", "label": "Decay", "min": 50, "max": 800, "value": 240, "unit": "ms", "midiSlot": 0}]}\n```'


def text(t: str) -> dict:
    return {"type": "message", "role": "assistant", "content": t, "delta": True}


@pytest.fixture()
def page(asked):
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("requestfailed", lambda r: errors.append(f"failed: {r.url}"))
        responses: list[str] = []
        pg.on("response", lambda r: responses.append(f"{r.status} {r.url}") if r.status >= 400 and "/favicon" not in r.url else None)
        pg.goto(asked.rig.url + "/app/ask/")
        pg.wait_for_selector("#box")
        pg.errors, pg.bad = errors, responses  # type: ignore[attr-defined]
        yield pg
        browser.close()
    assert errors == [], errors


def send(pg, words: str) -> None:
    pg.fill("#box textarea", words)
    pg.click("#send")


def test_ask_a_question_and_the_answer_and_a_card_appear(asked, page):
    asked.providers["claude"].script = [text("Here is a kick.\n\n"), text(BLOCK), text("\n\nTell me what to change.")]
    assert page.locator("#engine").input_value() == "claude"
    send(page, "make me a kick")
    page.wait_for_selector(".m.user .bubble")
    assert page.locator(".m.user .bubble").first.inner_text() == "make me a kick"
    page.wait_for_selector("text=Tell me what to change.")
    page.wait_for_selector(".zs-card .zs-title", timeout=5000)  # the old zpkt-surface block still draws, as a card
    assert page.locator(".zs-card .zs-title").first.inner_text() == "Kick: decay"
    assert page.bad == [], page.bad
    assert asked.ask.store.all_sessions()[0]["title"] == "make me a kick"


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


def test_a_session_opens_again_from_another_page_with_its_history(asked, page):
    asked.providers["claude"].script = [text("First answer."), Call("read_state")]
    send(page, "hello there")
    page.wait_for_selector("text=First answer.")
    sid = asked.ask.store.all_sessions()[0]["id"]
    asked.ask.wait_idle()
    other = page.context.new_page()  # a second device: the same server
    other.goto(f"{asked.rig.url}/app/ask/#s={sid}")
    other.wait_for_selector("text=First answer.")
    assert other.locator(".m.user .bubble").first.inner_text() == "hello there"
