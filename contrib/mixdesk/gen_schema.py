"""Write the mix desk's contracts in lib/contracts: its messages (protocol.py) and its made surfaces (surfaces.py).

.venv/bin/python contrib/mixdesk/gen_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol as P  # noqa: E402
import surfaces  # noqa: E402

CONTRACTS = HERE.parents[1] / "lib" / "contracts"
OUT = CONTRACTS / "mixdesk-message.schema.json"
SURFACE_OUT = CONTRACTS / "mixdesk-surface.schema.json"
SCHEMAS: dict[Path, tuple[Any, str]] = {
    OUT: (
        P.PageEvent,
        "The mix desk's messages: what the pager (inside Live) sends the server as UDP datagrams, and "
        "what the server streams to the page as server-sent events. Generated from contrib/mixdesk/protocol.py by "
        "contrib/mixdesk/gen_schema.py; do not edit by hand.",
    ),
    SURFACE_OUT: (
        surfaces.SurfaceFile,
        "A surface made for the mix desk (<sets_dir>/surfaces/<set>/<name>.json): a "
        "page of MiniLab controls and macros. Generated from contrib/mixdesk/surfaces.py by "
        "contrib/mixdesk/gen_schema.py; do not edit by hand.",
    ),
}


# Files whose object is open: a later version adds keys, and every reader and writer keeps them.
OPEN = {SURFACE_OUT}


def build(path: Path) -> dict[str, Any]:
    kind, description = SCHEMAS[path]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/becker929/zpkt/lib/contracts/{path.name}",
        "description": description,
        **TypeAdapter(kind).json_schema(),
    }
    if path in OPEN:
        schema["additionalProperties"] = True
    return schema


def text(path: Path = OUT) -> str:
    return json.dumps(build(path), indent=2) + "\n"


if __name__ == "__main__":
    for path in SCHEMAS:
        path.write_text(text(path))
        print(path)
