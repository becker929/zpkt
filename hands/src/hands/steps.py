"""Tell the studio app about a step, so it can take a screenshot of it, and log timings.

The studio (docs/studio.md) gives scripts a loopback-only endpoint in the environment:
STUDIO_STEP_URL, with its token in STUDIO_STEP_TOKEN. `report` posts one step there:
"major" for the moments worth a picture at the default level (a set opened, an export done, a
guard tripped), "minor" for the small steps in between. Without the variables it does nothing.
It never raises and gives up after 2 s: a missing screenshot must not stop a render.

`timing` appends a step's duration to <data_dir>/bench.jsonl, the log the render cost model in
docs/probe-packing-findings.md was fitted from.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from urllib.parse import urlsplit

from hands import config

TIMEOUT_S = 2.0
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback: never via a proxy


def report(caption: str, level: str = "minor", x: float | None = None, y: float | None = None) -> bool:
    """Post a step to the studio; True if it took it. `x`, `y`: a screen point to zoom into."""
    url, token = os.environ.get("STUDIO_STEP_URL"), os.environ.get("STUDIO_STEP_TOKEN")
    if not url or not token:
        return False
    try:
        if urlsplit(url).hostname not in _LOOPBACK:  # the token goes nowhere else
            return False
        body: dict[str, object] = {"caption": caption, "level": level}
        if x is not None and y is not None:
            body.update(x=x, y=y)
        request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with _opener.open(request, timeout=TIMEOUT_S) as reply:
            return 200 <= reply.status < 300
    except Exception:  # noqa: BLE001 - a report must never stop the work it describes
        return False


def timing(step: str, seconds: float, **fields) -> dict:
    """Append {"t", "step", "s", **fields} to <data_dir>/bench.jsonl and return it."""
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "s": round(seconds, 3), **fields}
    path = config.rig().data_dir / "bench.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row
