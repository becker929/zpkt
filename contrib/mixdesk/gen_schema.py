"""Write lib/contracts/mixdesk-message.schema.json from protocol.py's message types.

    hands/.venv/bin/python contrib/mixdesk/gen_schema.py
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

OUT = HERE.parents[1] / "lib" / "contracts" / "mixdesk-message.schema.json"
DESCRIPTION = (
    "The mix desk's messages: what the pager (inside Live) sends the server as UDP datagrams, and what the server "
    "streams to the page as server-sent events. Generated from contrib/mixdesk/protocol.py by "
    "contrib/mixdesk/gen_schema.py; do not edit by hand."
)


def build() -> dict[str, Any]:
    schema = TypeAdapter(P.PageEvent).json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/becker929/zpkt/lib/contracts/mixdesk-message.schema.json",
        "description": DESCRIPTION,
        **schema,
    }


def text() -> str:
    return json.dumps(build(), indent=2) + "\n"


if __name__ == "__main__":
    OUT.write_text(text())
    print(OUT)
