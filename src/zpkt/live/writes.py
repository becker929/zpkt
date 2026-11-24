"""Device parameters by raw value, a few to a call: the one way hands writes and reads them in bulk.

Each call touches one device and at most WRITE_CHUNK parameters (ableton-guide rule 2), and never reads back what it
wrote: a read in the call that wrote crashes Live (rule 1), so callers read back in a later call. A value is clamped
to the parameter's range; a parameter the device lacks, or one Live has disabled, is skipped and named in the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from zpkt.live.transport import McpTransport

WRITE_CHUNK = 16  # parameters written per call
READ_CHUNK = 20  # parameters read per call

_SET_RAW = """d = {device}
ps = {{p.name: p for p in d.parameters}}
bad = []
for n, v in {values!r}:
    p = ps.get(n)
    if p is None or not p.is_enabled:
        bad.append(n)
    else:
        p.value = max(p.min, min(p.max, v))
result = bad"""


def set_raw_code(device: str, values: Sequence[tuple[str, Any]]) -> str:
    """The LOM code that sets `values` (parameter name, raw value) on `device` (a LOM expression) in one call."""
    return _SET_RAW.format(device=device, values=list(values))


def set_raw(
    client: McpTransport, device: str, values: Sequence[tuple[str, Any]], chunk: int = WRITE_CHUNK
) -> list[str]:
    """Set raw values on `device`, `chunk` to a call; return the names it could not set."""
    skipped: list[str] = []
    for a in range(0, len(values), chunk):
        skipped += client.run(set_raw_code(device, values[a : a + chunk])) or []
    return skipped


def read_raw(client: McpTransport, device: str, chunk: int = READ_CHUNK) -> dict[str, list[Any]]:
    """Every parameter of `device`: {name: [shown, raw]}, `chunk` parameters to a call."""
    count = client.run(f"result = len({device}.parameters)")
    out: dict[str, list[Any]] = {}
    for a in range(0, count, chunk):
        rows = client.run(
            f"d = {device}\nresult = [[p.name, str(p), p.value] for p in list(d.parameters)[{a}:{a + chunk}]]"
        )
        for name, shown, raw in rows:
            out[name] = [shown, raw]
    return out
