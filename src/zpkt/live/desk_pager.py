"""Loading the mix desk's pager into Live and calling it: the code strings the app sends.

The pager (contrib/mixdesk/pager.py) runs inside Live's Python and drives the MiniLab. Live loads it by file path, under
the name MODULE, and a reload hands the old desk's monitor and page to the new one. The app owns the connection and
passes it in; this module only builds the code and runs it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zpkt.live.transport import McpTransport

MODULE = "zpkt_mixdesk_pager"  # the pager's name in Live's sys.modules


def start_code(pager_file: Path, config: dict[str, Any], udp_port: int) -> str:
    """The code that (re)loads the pager and starts it, handing the old desk's monitor and page over."""
    return (
        "import importlib.util, sys, json\n"
        f"spec = importlib.util.spec_from_file_location({MODULE!r}, {str(pager_file)!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        f"old = sys.modules.get({MODULE!r})\n"
        "if old is not None and getattr(old, 'DESK', None) is not None:\n"
        "    d = old.DESK\n"
        "    m.CARRY = {'main_saved': getattr(d, 'main_saved', None), 'slot': getattr(d, 'monitor_slot', 'W'), "
        "'ref': getattr(d, 'monitor_ref', 'C1'), 'page': d.page, 'v': getattr(old, 'SLOTS_V', 1)}\n"
        "    d.stop()\n"
        f"sys.modules[{MODULE!r}] = m\n"
        f"result = m.start(song, json.loads({json.dumps(config)!r}), {udp_port})\n"
    )


def call_code(expr: str) -> str:
    """An expression on the running pager's desk; None when no pager runs."""
    return f"import sys\nm = sys.modules.get({MODULE!r})\nresult = {expr} if m is not None and m.DESK is not None else None"


def start(live: McpTransport, pager_file: Path, config: dict[str, Any], udp_port: int) -> Any:
    """Start the pager in Live; its snapshot."""
    return live.run(start_code(pager_file, config, udp_port))


def call(live: McpTransport, expr: str) -> Any:
    """Run `expr` on the pager's desk (for example "m.DESK.arm(2)"); None when no pager runs."""
    return live.run(call_code(expr))
