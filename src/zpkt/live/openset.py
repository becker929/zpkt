"""Which set Live has open: the name the app compares with the page's set (the wrong-set guard)."""

from __future__ import annotations

from pathlib import Path

from zpkt.live.hold import SET_PATH
from zpkt.live.transport import McpTransport


def open_set_name(live: McpTransport) -> str:
    """The open set's file name without its extension; "" when Live does not say (an unsaved set)."""
    path = str(live.run(SET_PATH) or "")
    return Path(path).stem if path else ""
