"""Write lib/contracts/verdict.schema.json from taste's Verdict model.

    uv run python scripts/gen_schema.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from taste.models import Verdict

OUT = Path(__file__).resolve().parents[2] / "lib" / "contracts" / "verdict.schema.json"


def build() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/becker929/zpkt/lib/contracts/verdict.schema.json",
        **{**Verdict.model_json_schema(mode="serialization"),
           "description": "taste's judgment of one render. Generated from taste/src/taste/models.py — do not edit by hand."},
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}", file=sys.stderr)
