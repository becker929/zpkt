"""The page in WebKit (Safari's engine) at an iPhone's size: it loads clean, pages back in place, and a whole turn
comes round. The phone in the car is an iPhone, so this is the browser that matters most."""

import pytest

from conftest import IPHONE_15, open_page
from test_turn import is_mic, is_playback
from test_window import FIRST_VISIBLE, TOP_OF

pytestmark = pytest.mark.ui

# Scroll to the very top and stay there for three frames. Blocks near the top draw at their real size as they come
# into view and the view keeps the reader's place meanwhile, so one `scrollTop = 0` can leave the Load earlier button
# half hidden; Playwright would then scroll it into view itself, and in WebKit that scroll can land after the view
# has already compensated for the older page.
AT_TOP = """() => new Promise((resolve) => {
  const chat = document.getElementById('chat');
  let still = 0;
  const tick = () => {
    chat.scrollTop = 0;
    still = chat.scrollTop === 0 ? still + 1 : 0;
    if (still >= 3) resolve(true); else requestAnimationFrame(tick);
  };
  tick();
})"""


@pytest.fixture
async def iphone(webkit, fake):
    page = await open_page(webkit, fake, device=IPHONE_15)
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_safari_loads_and_pages_back_in_place(webkit, fake):
    fake.seed_history(300)
    page = await open_page(webkit, fake, device=IPHONE_15)
    try:
        assert await page.messages_in_dom() == 40
        for _ in range(2):
            await page.wait("() => !document.getElementById('load-earlier').hidden")
            await page.wait(AT_TOP)
            anchor = await page.js(FIRST_VISIBLE)
            before = await page.js(TOP_OF, anchor)
            await page.page.click("#load-earlier")
            await page.wait("() => !document.getElementById('load-earlier').classList.contains('is-loading')", timeout=5000)
            after = await page.js(TOP_OF, anchor)
            assert abs(after - before) <= 1, f"the message you were reading moved from {before} to {after}"
        assert await page.messages_in_dom() == 60
        assert page.errors == [], f"console errors: {page.errors}"
    finally:
        await page.page.context.close()


async def test_safari_a_typed_turn_comes_round(iphone, fake):
    page = iphone
    fake.turn_frames = 0
    await page.page.tap("#turn")
    await fake.expect(lambda m: m["type"] == "start")
    await fake.expect(is_mic("open"))
    await page.page.tap("#keyboard")
    await page.page.fill("#composer-input", "Brighter hats")
    await page.page.press("#composer-input", "Enter")
    said = await fake.expect(lambda m: m["type"] == "say")
    assert said["text"] == "Brighter hats"
    await fake.expect(is_playback("idle", 2), timeout=20)
    await fake.expect(is_mic("open", "t2"))
