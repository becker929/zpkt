"""The CI guard that turns a skipped browser test into a failure (tests/conftest.py)."""

from __future__ import annotations

import pytest

from tests.conftest import browser_required, is_browser_skip


def test_browser_skip_reasons_are_recognised():
    assert is_browser_skip("WebKit is not available: Executable doesn't exist")
    assert is_browser_skip("Skipped: could not import 'playwright.sync_api'")
    assert not is_browser_skip("no MiniLab on this machine")


@pytest.mark.parametrize(("value", "expected"), [("", False), ("0", False), ("1", True), ("yes", True)])
def test_switch_reads_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ZPKT_REQUIRE_BROWSER", value)
    assert browser_required() is expected

