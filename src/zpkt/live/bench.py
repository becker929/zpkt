"""The bench log: how long Live steps take, appended to <data_dir>/bench.jsonl.

The render cost model in docs/probe-packing-findings.md was fitted from this log.
"""

from __future__ import annotations

import json
import time
from typing import Any

from hands import config


def timing(step: str, seconds: float, **fields: Any) -> dict[str, Any]:
    """Append {"t", "step", "s", **fields} to <data_dir>/bench.jsonl and return it."""
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "s": round(seconds, 3), **fields}
    path = config.rig().data_dir / "bench.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row
