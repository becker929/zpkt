"""Loading the page over a slow link: the chat shows before the socket is up, and every module is asked for up front
under the version the page names (studio/assets.py)."""

import pytest

from conftest import open_page

pytestmark = pytest.mark.ui

IN_DOM = "document.querySelectorAll('#messages [data-seq]').length"
WELCOMED = "document.getElementById('sheet-foot').textContent.includes('conversation')"     # main.js welcome()


@pytest.fixture
async def held(chromium, fake):
    """The page on a chat of 100 messages, its socket open and its hello sent, with the welcome held back."""
    fake.seed_history(100)
    fake.welcome_gate.clear()
    page = await open_page(chromium, fake)
    yield page
    fake.welcome_gate.set()
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_history_shows_before_the_socket_welcomes(held, fake):
    page = held
    newest = fake.messages[-1]["seq"]
    assert await page.js(IN_DOM) == 40
    assert await page.js(f"!!document.querySelector('[data-seq=\"{newest}\"]')")
    assert not await page.js(WELCOMED)

    fake.welcome_gate.set()                   # the welcome brings the same page: nothing is added twice
    await page.wait(WELCOMED)
    msg = await fake.upsert("agent", text="Here it is.", role="reply")
    await page.wait(f"!!document.querySelector('[data-seq=\"{msg['seq']}\"]')")
    assert await page.js(IN_DOM) == 41


async def test_modules_are_versioned_and_preloaded(phone, fake):
    version = fake.assets.version()
    loaded = await phone.js("performance.getEntriesByType('resource').map((e) => new URL(e.name).pathname)"
                            ".filter((p) => p.startsWith('/studio/static/'))")
    preloaded = await phone.js("[...document.querySelectorAll('link[rel=modulepreload]')].map((l) => new URL(l.href).pathname)")
    assert loaded and all(p.startswith(f"/studio/static/{version}/") for p in loaded)
    modules = {p for p in loaded if p.endswith(".js") and not p.endswith("mic-worklet.js")}
    assert modules <= set(preloaded), f"found only through imports: {sorted(modules - set(preloaded))}"
