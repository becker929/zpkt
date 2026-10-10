"""The chat window: at most WINDOW_CAP messages in the DOM however long the conversation, paging back in time
without losing your place, and back to the newest."""

import pytest

from conftest import open_page

pytestmark = pytest.mark.ui

CAP = 60                       # store.js WINDOW_CAP
FIRST_PAGE = 40                # what the Mac's welcome carries

# The largest number of messages the DOM held at any moment, watched from inside the page.
WATCH = """() => {
  window.__most = 0;
  const count = () => { window.__most = Math.max(window.__most, document.querySelectorAll('#messages [data-seq]').length); };
  new MutationObserver(count).observe(document.getElementById('messages'), {childList: true, subtree: true});
  count();
}"""

# Where a message sits on screen, relative to the top of the chat.
TOP_OF = """(seq) => document.querySelector(`[data-seq="${seq}"]`).getBoundingClientRect().top
                     - document.getElementById('chat').getBoundingClientRect().top"""

FIRST_VISIBLE = """() => {
  const top = document.getElementById('chat').getBoundingClientRect().top;
  const el = [...document.querySelectorAll('#messages [data-seq]')].find((e) => e.getBoundingClientRect().bottom > top + 1
                                                                            && e.getBoundingClientRect().height > 0);
  return Number(el.dataset.seq);
}"""

AT_BOTTOM = """() => { const c = document.getElementById('chat'); return c.scrollHeight - c.scrollTop - c.clientHeight < 4; }"""


@pytest.fixture
async def long_chat(chromium, fake):
    fake.seed_history(1000)
    page = await open_page(chromium, fake)
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_a_thousand_live_messages_keep_the_window_at_its_cap(long_chat, fake):
    page = long_chat
    assert await page.messages_in_dom() == FIRST_PAGE
    assert await page.js(AT_BOTTOM)
    await page.js(WATCH)
    for i in range(1000):
        kind, data = ("activity", dict(tool="Bash", title=f"Live step {i}", status="ok", ms=i)) if i % 3 else \
            ("agent", dict(text=f"Live narration {i}", role="narration", audio=None, duration=None, streaming=False))
        await fake.upsert(kind, **data)
    newest = fake.messages[-1]["seq"]
    await page.wait(f"() => document.querySelector('[data-seq=\"{newest}\"]')")
    assert await page.js("window.__most") <= CAP
    assert await page.messages_in_dom() == CAP
    assert await page.js("window.studio.store.size") == CAP
    assert await page.js(AT_BOTTOM), "a reader at the bottom stays at the bottom"
    # The oldest live ones were dropped as the newest came in; the window is the newest 60.
    shown = await page.js("[...document.querySelectorAll('#messages [data-seq]')].map((e) => Number(e.dataset.seq))")
    assert shown == [m["seq"] for m in fake.messages[-CAP:]]


async def test_load_earlier_shows_a_spinner_and_keeps_your_place(long_chat, fake):
    page = long_chat
    fake.page_delay = 0.8                                     # slow enough to see the spinner
    await page.js("document.getElementById('chat').scrollTop = 0")
    await page.wait("() => !document.getElementById('load-earlier').hidden")
    anchor = await page.js(FIRST_VISIBLE)
    before = await page.js(TOP_OF, anchor)

    await page.page.click("#load-earlier")
    await page.wait("() => document.getElementById('load-earlier').classList.contains('is-loading')")
    assert await page.js("getComputedStyle(document.querySelector('#load-earlier .spinner')).display") != "none"
    assert await page.js("document.getElementById('load-earlier').disabled")
    await page.wait("() => !document.getElementById('load-earlier').classList.contains('is-loading')", timeout=5000)

    after = await page.js(TOP_OF, anchor)
    assert abs(after - before) <= 1, f"the message you were reading moved from {before} to {after}"
    assert await page.messages_in_dom() == CAP
    # 40 + 30 did not fit: the newest 10 left the window, so it is no longer at the newest.
    assert await page.js("window.studio.store.detached")
    await page.wait("() => !document.getElementById('jump').hidden")

    # Two more pages back (scrolling up to the button each time): still capped, still in place.
    for _ in range(2):
        await page.js("document.getElementById('chat').scrollTop = 0")
        await page.wait("() => new Promise((resolve) => requestAnimationFrame(() => resolve(true)))")
        anchor = await page.js(FIRST_VISIBLE)
        before = await page.js(TOP_OF, anchor)
        await page.page.click("#load-earlier")
        await page.wait("() => !document.getElementById('load-earlier').classList.contains('is-loading')", timeout=5000)
        assert abs(await page.js(TOP_OF, anchor) - before) <= 1
        assert await page.messages_in_dom() == CAP

    # Jump to latest: the newest page comes back and the chat is at its end.
    fake.page_delay = 0
    await page.page.click("#jump")
    newest = fake.messages[-1]["seq"]
    await page.wait(f"() => document.querySelector('[data-seq=\"{newest}\"]')")
    await page.wait(AT_BOTTOM)
    assert not await page.js("window.studio.store.detached")
    await page.wait("() => document.getElementById('jump').hidden")
    assert await page.messages_in_dom() <= CAP


async def test_new_messages_while_reading_back_offer_a_jump(long_chat, fake):
    page = long_chat
    await page.js("document.getElementById('chat').scrollTop = 0")
    await page.wait("() => document.getElementById('jump').hidden")
    anchor = await page.js(FIRST_VISIBLE)
    before = await page.js(TOP_OF, anchor)
    for i in range(3):
        await fake.upsert("notice", level="info", text=f"New notice {i}")
    await page.wait("() => !document.getElementById('jump').hidden")
    assert await page.js("document.getElementById('jump-count').textContent") == "3"
    assert abs(await page.js(TOP_OF, anchor) - before) <= 1, "new messages below do not move what you are reading"
    await page.page.click("#jump")
    await page.wait(AT_BOTTOM)
    await page.wait("() => document.getElementById('jump').hidden")


async def test_reading_the_oldest_message_detaches_instead_of_dropping_it(long_chat, fake):
    page = long_chat
    # Fill the window to its cap, then read the oldest message in it.
    for i in range(CAP - FIRST_PAGE):
        await fake.upsert("notice", level="info", text=f"Filler {i}")
    await page.wait(f"() => document.querySelectorAll('#messages [data-seq]').length === {CAP}")
    oldest = await page.js("Number(document.querySelector('#messages [data-seq]').dataset.seq)")
    await page.js("document.getElementById('chat').scrollTop = 0")
    await fake.upsert("notice", level="info", text="One more")
    await page.wait("() => !document.getElementById('jump').hidden")
    assert await page.js("window.studio.store.detached")
    assert await page.js(f"!!document.querySelector('[data-seq=\"{oldest}\"]')"), "what you read stays"
    assert await page.messages_in_dom() == CAP


async def test_reconnecting_says_hello_again_and_takes_the_mic_back(phone, fake):
    page = phone
    fake.turn_frames = 0
    await page.page.click("#turn")
    await fake.expect(lambda m: m["type"] == "mic" and m["state"] == "open")
    mark = len(fake.inbox)
    await fake.upsert("notice", level="info", text="Before the drop")
    for ws in list(fake.pages):
        await ws.close()
    await page.wait("() => document.getElementById('conn').dataset.state !== 'open'")
    await page.wait("() => ['offline'].includes(document.getElementById('phase').dataset.phase)")
    # Back: hello again, a welcome that replaces the window, and the mic and speaker taken back.
    await fake.expect(lambda m: m["type"] == "hello", since=mark, timeout=15)
    await fake.expect(lambda m: m["type"] == "start", since=mark)
    await fake.expect(lambda m: m["type"] == "mic" and m["state"] == "open", since=mark)
    await page.wait("() => document.getElementById('conn').dataset.state === 'open'")
    assert await page.js("document.querySelector('.msg--notice p').textContent") == "Before the drop"


async def test_a_new_conversation_from_the_menu(phone, fake):
    page = phone
    await fake.upsert("notice", level="info", text="From the old conversation")
    await page.wait("() => document.querySelector('.msg--notice')")
    await page.page.click("#menu-open")
    await page.page.click("#new-conversation")
    assert await page.js("document.getElementById('new-conversation-title').textContent") == "Tap again to start afresh"
    await page.page.click("#new-conversation")
    await page.wait("() => !document.getElementById('menu').open")
    await page.wait("() => !document.querySelector('#messages [data-seq]') && !document.getElementById('empty').hidden")
