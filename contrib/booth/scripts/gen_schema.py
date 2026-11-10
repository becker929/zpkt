"""Write lib/contracts/score.schema.json from the booth's Score model; tests/test_contract.py fails if it is stale.

    uv run python scripts/gen_schema.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from booth.score import Score

CONTRACTS = Path(__file__).resolve().parents[3] / "lib" / "contracts"
DESCRIPTION = ("A short piece for the booth to build in Live (docs/design/bluesky-bot.md). "
               "Generated from contrib/booth/src/booth/score.py — do not edit by hand.")


def build() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/becker929/zpkt/lib/contracts/score.schema.json",
        **{**Score.model_json_schema(mode="serialization"), "description": DESCRIPTION},
    }


if __name__ == "__main__":
    (CONTRACTS / "score.schema.json").write_text(json.dumps(build(), indent=2) + "\n")
    print("wrote score.schema.json", file=sys.stderr)
