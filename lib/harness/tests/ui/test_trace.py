"""The trace: Claude's thinking, tool calls and screenshots folded into one bubble until another kind of message
breaks the run; folded by default, unfolding to the items in order, and kept in place when pages come and go."""

import pytest

from conftest import IPHONE_15, open_page
from test_webkit import AT_TOP
from test_window import FIRST_VISIBLE, TOP_OF

pytestmark = pytest.mark.ui

# Each trace on the page: its items' kinds and seqs in order, whether it is open, and its folded line.
TRACES = """() => [...document.querySelectorAll('#messages > .trace')].map((t) => ({
  items: [...t.querySelectorAll('.trace-list > [data-seq]')].map((i) => [i.dataset.kind, Number(i.dataset.seq)]),
  open: t.querySelector('.trace-box').open,
  status: t.dataset.status,
  title: t.querySelector('.trace-title').textContent,
  meta: t.querySelector('.trace-meta').textContent,
}))"""

# The kinds of the blocks in the list, in order (a trace counts as one).
BLOCKS = """() => [...document.querySelectorAll('#messages > li')].map((b) => b.classList.contains('trace') ? 'trace' : b.dataset.kind)"""

THOUGHT = "**Checking the chain**\n\nThe kick goes through a compressor first; its threshold sets how loud it can get."


async def a_turn_of_work(fake):
    """Thinking, two tool calls around a screenshot pair, a reply, then thinking again."""
    await fake.upsert("user", text="louder kick", source="typed", audio=None, duration=None)
    think = await fake.upsert("thinking", text="**Checking", streaming=True)
    await fake.update(think, text=THOUGHT, streaming=False)
    read = await fake.upsert("activity", tool="Read", title="Read kick-chain.json", status="ok", ms=120, detail="kick")
    shot = await fake.shot("major", "The kick’s chain")
    bash = await fake.upsert("activity", tool="Bash", title="Render the A/B", status="running", detail="render.py")
    return think, read, shot, bash


@pytest.fixture
async def page(chromium, fake):
    page = await open_page(chromium, fake)
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_thinking_tools_and_shots_share_one_folded_trace_until_another_kind_breaks_it(page, fake):
    think, read, shot, bash = await a_turn_of_work(fake)
    await page.wait(f"() => document.querySelector('[data-seq=\"{bash['seq']}\"]')")
    [trace] = await page.js(TRACES)
    assert trace["items"] == [["thinking", think["seq"]], ["activity", read["seq"]], ["shots", shot["seq"]],
                              ["activity", bash["seq"]]]
    # Folded by default: one line with the step running now, the counts and a spinner.
    assert not trace["open"] and trace["status"] == "running"
    assert trace["title"] == "Render the A/B" and trace["meta"] == "2 steps · 1 shot"
    assert await page.js("getComputedStyle(document.querySelector('.trace-head .spinner')).display") != "none"
    assert await page.js(f"document.querySelector('[data-seq=\"{shot['seq']}\"]').getBoundingClientRect().height") == 0
    assert await page.js("!document.querySelector('.trace-thumb').hidden"), "a folded trace shows its latest zoom"

    # The step fails: the folded line says so.
    await fake.update(bash, status="error", ms=900)
    await page.wait("() => document.querySelector('.trace').dataset.status === 'error'")
    assert await page.js("getComputedStyle(document.querySelector('.trace-head .st-error')).display") != "none"

    # A reply breaks the run; the thinking after it starts a new trace, which names the thought.
    await fake.upsert("agent", text="It's louder now.", role="reply", audio=None, duration=None, streaming=False)
    later = await fake.upsert("thinking", text="**Comparing the levels**\n\nB is three dB up.", streaming=False)
    await page.wait(f"() => document.querySelector('[data-seq=\"{later['seq']}\"]')")
    assert await page.js(BLOCKS) == ["user", "trace", "agent", "trace"]
    first, second = await page.js(TRACES)
    assert len(first["items"]) == 4 and second["items"] == [["thinking", later["seq"]]]
    assert second["title"] == "Comparing the levels" and second["meta"] == "1 thought" and second["status"] == "ok"

    # A narration and a notice break a run too; music as well.
    for kind, data in [("agent", dict(text="Rendering", role="narration", audio=None, duration=None,
                                      streaming=False)),
                       ("activity", dict(tool="Bash", title="Step", status="ok", ms=1)),
                       ("notice", dict(level="info", text="Hello")),
                       ("activity", dict(tool="Bash", title="Step 2", status="ok", ms=1))]:
        await fake.upsert(kind, **data)
    await page.wait(f"() => document.querySelector('[data-seq=\"{fake.messages[-1]['seq']}\"]')")
    assert await page.js(BLOCKS) == ["user", "trace", "agent", "trace", "agent", "trace", "notice", "trace"]


async def test_unfolded_the_items_show_in_order_and_a_shot_opens_the_lightbox(page, fake):
    think, read, shot, bash = await a_turn_of_work(fake)
    await page.wait(f"() => document.querySelector('[data-seq=\"{bash['seq']}\"]')")
    await page.page.click(".trace-head")
    await page.wait("() => document.querySelector('.trace-box').open")
    # In order, each drawn: the thought (its heading and dimmed text), the steps and the screenshot pair.
    tops = await page.js("""(seqs) => seqs.map((s) => document.querySelector(`[data-seq="${s}"]`).getBoundingClientRect())
                                         .map((r) => r.height > 0 ? r.top : null)""",
                         [think["seq"], read["seq"], shot["seq"], bash["seq"]])
    assert None not in tops and tops == sorted(tops)
    assert await page.js("document.querySelector('.think strong').textContent") == "Checking the chain"
    assert (await page.js("document.querySelector('.think p').textContent")).startswith("The kick goes through")
    think_color = await page.js("getComputedStyle(document.querySelector('.think p')).color")
    reply_color = await page.js("getComputedStyle(document.querySelector('.msg--user .inline-text')).color")
    assert think_color != reply_color, "thinking is dimmed"
    assert await page.js("document.querySelector('.trace-thumb').getBoundingClientRect().width") == 0

    # The zoom, from inside the trace, opens in the lightbox.
    await page.page.click(f"[data-seq=\"{shot['seq']}\"] .shot--zoom")
    await page.wait("() => document.getElementById('lightbox').open")
    assert await page.js("document.getElementById('lightbox-img').getAttribute('src')") == shot["data"]["zoom"]["url"]
    assert await page.js("document.getElementById('lightbox-caption').textContent") == "The kick’s chain"
    await page.page.keyboard.press("Escape")
    await page.wait("() => !document.getElementById('lightbox').open")

    # Updates and new items patch the open trace in place: it stays open.
    await fake.update(bash, status="ok", ms=2300)
    more = await fake.upsert("thinking", text="Done; now say it.", streaming=False)
    await page.wait(f"() => document.querySelector('[data-seq=\"{more['seq']}\"]')?.getBoundingClientRect().height > 0")
    [trace] = await page.js(TRACES)
    assert trace["open"] and trace["status"] == "ok" and len(trace["items"]) == 5
    # Folding it again hides the items.
    await page.page.click(".trace-head")
    await page.wait("() => !document.querySelector('.trace-box').open")


async def test_the_screenshot_level_hides_shots_inside_a_trace(page, fake):
    await fake.upsert("activity", tool="Bash", title="Render", status="ok", ms=5)
    for level in ("major", "minor", "firehose"):
        await fake.shot(level, level.title())           # sent live only up to the page's level, as the Mac does
    await fake.upsert("notice", level="info", text="Between")
    await fake.shot("minor", "A shot on its own")
    await page.page.reload()                             # history has every level
    await page.wait("() => document.querySelectorAll('.trace').length === 2")
    first, alone = await page.js(TRACES)
    assert first["meta"] == "1 step · 1 shot" and alone["meta"] == ""
    assert await page.js("getComputedStyle(document.querySelectorAll('.trace')[1]).display") == "none"
    await page.page.select_option("#shots", "none")
    await page.wait("() => document.querySelector('.trace-meta').textContent === '1 step'")
    await page.page.select_option("#shots", "firehose")
    await page.wait("() => document.querySelector('.trace-meta').textContent === '1 step · 3 shots'")
    assert await page.js("getComputedStyle(document.querySelectorAll('.trace')[1]).display") != "none"


def seed_split_trace(fake):
    """20 notices, a trace of 30 items, 25 replies: the first page (40) holds the trace's newest 15. The replies are
    tall enough that the window, once it drops its newest 10 for the older page, can still keep the reader's place."""
    for i in range(20):
        fake.add("notice", turn="t0", level="info", text=f"Before {i}")
    for i in range(30):
        if i % 3 == 0:
            fake.add("thinking", turn="t0", text=f"**Thought {i}**\n\nA thought about step {i}, long enough to wrap "
                     "onto a second line on a phone.", streaming=False)
        else:
            fake.add("activity", turn="t0", tool="Bash", title=f"Step {i}", status="ok", ms=10 + i)
    for i in range(25):
        fake.add("agent", turn="t1", text=f"After {i}: the hats sit better now.", role="note", audio=None,
                 duration=None, streaming=False)
    return [m["seq"] for m in fake.messages[20:50]]


@pytest.mark.parametrize("unfold", [False, True], ids=["folded", "unfolded"])
async def test_a_trace_split_across_pages_grows_at_its_front_in_place(chromium, fake, unfold):
    trace_seqs = seed_split_trace(fake)
    page = await open_page(chromium, fake)
    try:
        [trace] = await page.js(TRACES)
        assert [s for _, s in trace["items"]] == trace_seqs[15:]
        if unfold:
            await page.js("document.querySelector('.trace-box').open = true")
            await page.wait("() => document.querySelector('.trace-list > [data-seq]').getBoundingClientRect().height > 0")
        await page.wait("() => !document.getElementById('load-earlier').hidden")
        await page.wait(AT_TOP)
        anchor = await page.js(FIRST_VISIBLE)
        if unfold:
            assert anchor in trace_seqs, "the reader is inside the open trace"
        before = await page.js(TOP_OF, anchor)
        await page.page.click("#load-earlier")
        await page.wait("() => !document.getElementById('load-earlier').classList.contains('is-loading')", timeout=5000)
        await page.wait("() => new Promise((resolve) => requestAnimationFrame(() => resolve(true)))")
        after = await page.js(TOP_OF, anchor)
        assert abs(after - before) <= 1, f"the message you were reading moved from {before} to {after}"
        # One trace, now with all 30 items, and still folded or unfolded as the reader left it.
        [trace] = await page.js(TRACES)
        assert [s for _, s in trace["items"]] == trace_seqs and trace["open"] == unfold
        assert trace["meta"] == "20 steps"

        # Jump to latest drops the trace's older half and the page brings it back: the fold is remembered.
        await page.page.click("#jump")
        await page.wait("() => !window.studio.store.detached")
        await page.wait(AT_TOP)
        await page.page.click("#load-earlier")
        await page.wait(f"() => document.querySelector('[data-seq=\"{trace_seqs[0]}\"]')", timeout=5000)
        [trace] = await page.js(TRACES)
        assert trace["open"] == unfold
        assert page.errors == [], f"console errors: {page.errors}"
    finally:
        await page.page.context.close()


async def test_safari_folds_unfolds_and_opens_a_shot_from_a_trace(webkit, fake):
    page = await open_page(webkit, fake, device=IPHONE_15)
    try:
        think, read, shot, bash = await a_turn_of_work(fake)
        await page.wait(f"() => document.querySelector('[data-seq=\"{bash['seq']}\"]')")
        assert not (await page.js(TRACES))[0]["open"]
        await page.page.tap(".trace-head")
        await page.wait(f"() => document.querySelector('[data-seq=\"{shot['seq']}\"] img')?.complete"
                        f" && document.querySelector('[data-seq=\"{shot['seq']}\"]').getBoundingClientRect().height > 40")
        await page.page.tap(f"[data-seq=\"{shot['seq']}\"] .shot--full")
        await page.wait("() => document.getElementById('lightbox').open")
        assert await page.js("document.getElementById('lightbox-img').getAttribute('src')") == shot["data"]["full"]["url"]
        assert page.errors == [], f"console errors: {page.errors}"
    finally:
        await page.page.context.close()
