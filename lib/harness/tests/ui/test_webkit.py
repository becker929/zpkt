"""The page in WebKit (Safari's engine) at an iPhone's size: it loads clean, pages back in place, and a whole turn
comes round. The phone in the car is an iPhone, so this is the browser that matters most."""

import pytest

from conftest import IPHONE_15, open_page
from heard import find_passes, heard
from test_heard import render, the_ear
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


async def test_safari_the_ear_hears_a_render_to_the_sample(iphone, fake):
    # The capture shim works in WebKit too: a render the Mac plays is recorded, and lines up with the file.
    page = iphone
    fake.turn_frames = 0
    music = await fake.present_music()
    await page.page.tap("#turn")
    await fake.expect(is_mic("open"))
    mark = len(fake.inbox)
    await fake.play(music["seq"], 2)
    await fake.expect(is_playback("idle", 1), since=mark, timeout=15)
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]
    ref = render(fake, ear)
    passes = find_passes(ear.samples, ref)
    assert len(passes.starts) == 2 and min(passes.scores) > 0.99, passes
    assert passes.starts[1] - passes.starts[0] == len(ref)
    assert abs(ear.time(passes.starts[0]) - entry["t0"]) < 1.5 / ear.rate


@pytest.mark.parametrize("width", [320, 375, 393, 430])
async def test_nothing_pushes_the_page_sideways_at_any_iphone_width(webkit, fake, width):
    """Every iPhone width (320 is a small one with Display Zoom), every screenshot level: the page is as wide as the
    screen, and the screenshots chip still shows something."""
    fake.seed_history(30)
    page = await open_page(webkit, fake, device={**IPHONE_15, "viewport": {"width": width, "height": 700}})
    for level in ("none", "major", "minor", "firehose"):
        await page.page.select_option("#shots", level)
        assert await page.js("document.documentElement.scrollWidth") == width, level
        assert await page.js("document.querySelector('.chip--select').getBoundingClientRect().width") >= 44, level
    assert page.errors == []
    await page.page.context.close()


async def test_a_folded_caption_shows_its_first_line_and_typing_makes_room(iphone, fake):
    page = iphone
    msg = await fake.upsert("agent", text="I rendered the kick at its current level and three dB louder.", role="reply",
                            audio=None, duration=None, streaming=False)
    row = f'[data-seq="{msg["seq"]}"]'
    await page.wait(f"() => document.querySelector('{row} .peek')?.textContent")
    shown = f"[...document.querySelectorAll('{row} summary > span')].filter((s) => getComputedStyle(s).display !== 'none').map((s) => s.className)"
    assert await page.js(shown) == ["peek"]
    await page.page.click(f"{row} summary")
    assert await page.js(shown) == ["label"]                    # open: the whole text below, "Caption" above it

    before = await page.js("document.querySelector('.dock').getBoundingClientRect().height")
    await page.page.click("#keyboard")
    after = await page.js("document.querySelector('.dock').getBoundingClientRect().height")
    assert after < before, (before, after)
    assert await page.js("document.getElementById('turn').getBoundingClientRect().width") >= 44   # still a target
