"""An agent's batch (live.change) in the page's History (WebKit, on FakeLive): one row that says who, why and how
much, and one Undo that takes the whole batch back. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.test_desk_touch import open_lead
from tests.app.test_live_change import BATCH, KICK, names, no_waiting  # noqa: F401  (the fixture)
from zpkt.app.bus import Command

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def test_a_batch_is_one_history_row_with_who_why_and_a_count_and_one_undo(browser, rig):
    pg = open_lead(browser, rig)
    assert rig.desk.bus.submit(Command("live.change", "agent", BATCH, group="ask-s1"))[0] == 200
    pg.wait_for_function("document.querySelectorAll('#hrows .he.row').length === 1")
    row = pg.locator("#hrows .he.row")
    text = " ".join(row.inner_text().split())
    assert "warmer kick" in text and "3 controls, 2 devices" in text and "ask-s1" not in text
    assert row.locator(".who.agent").inner_text() == "agent"
    assert pg.locator("#hrows .he.cp").count() == 1  # the version saved before it, as a flag
    pg.locator("#kundo").click()
    pg.wait_for_function("document.querySelectorAll('#hrows .he.undone').length === 1")
    assert names(rig, KICK) == ["desk EQ", "desk Sat", "desk Glue"]
    assert pg.errors == []  # type: ignore[attr-defined]
