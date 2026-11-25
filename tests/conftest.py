"""Shared pytest setup: in CI a browser test that cannot run fails instead of skipping.

The Playwright tests skip when WebKit (or the playwright package) is missing, which is right on a laptop. CI sets
ZPKT_REQUIRE_BROWSER=1 in the job that installs the browser, so a broken install turns red rather than green.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from hypothesis import settings

# One profile for every property test: few examples and no per-example deadline (the machine is shared and busy).
settings.register_profile("zpkt", max_examples=50, deadline=None)
settings.load_profile("zpkt")

BROWSER_WORDS = ("webkit", "playwright")


def browser_required() -> bool:
    return os.environ.get("ZPKT_REQUIRE_BROWSER", "") not in ("", "0")


def is_browser_skip(reason: str) -> bool:
    low = reason.lower()
    return any(word in low for word in BROWSER_WORDS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    if not browser_required() or not report.skipped:
        return
    longrepr = report.longrepr
    reason = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
    if is_browser_skip(reason):
        report.outcome = "failed"
        report.longrepr = f"ZPKT_REQUIRE_BROWSER is set, but the browser test was skipped: {reason}"
