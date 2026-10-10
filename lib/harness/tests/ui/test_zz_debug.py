import pytest

from conftest import open_page
from test_window import FIRST_VISIBLE, TOP_OF

pytestmark = pytest.mark.ui

TOP = """() => [...document.getElementById('messages').children].slice(0, 6).map((b) => {
  const r = b.getBoundingClientRect();
  const seqs = b.dataset.seq ?? [...b.querySelectorAll('[data-seq]')].map((e) => e.dataset.seq).join('+');
  return `${b.className}:${seqs}@${Math.round(r.top)}/${Math.round(r.height)}`;
}).join('  ')"""


async def test_debug(chromium, fake):
    fake.seed_history(1000)
    page = await open_page(chromium, fake)
    for n in range(3):
        await page.js("document.getElementById('chat').scrollTop = 0")
        await page.wait("() => new Promise((resolve) => requestAnimationFrame(() => resolve(true)))")
        anchor = await page.js(FIRST_VISIBLE)
        print("before", n, anchor, await page.js(TOP_OF, anchor), await page.js(TOP))
        await page.page.click("#load-earlier")
        await page.wait("() => !document.getElementById('load-earlier').classList.contains('is-loading')", timeout=5000)
        await page.wait("() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))))")
        print("after ", n, anchor, await page.js(TOP_OF, anchor), await page.js(TOP))
