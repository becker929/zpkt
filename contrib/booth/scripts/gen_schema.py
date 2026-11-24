"""Write lib/contracts/score.schema.json and the booth API's schemas (booth-*.schema.json) from the booth's models;
tests/test_contract.py fails if any is stale.

    uv run python scripts/gen_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from booth.contract import SCHEMAS
from booth.score import Score

CONTRACTS = Path(__file__).resolve().parents[3] / "lib" / "contracts"
DESCRIPTION = (
    "A short piece for the booth to build in Live (contrib/docs/design/bluesky-bot.md). "
    "Generated from contrib/booth/src/booth/score.py — do not edit by hand."
)
API_DESCRIPTION = "Generated from contrib/booth/src/booth/contract.py ({model}) — do not edit by hand."


def build() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/becker929/zpkt/lib/contracts/score.schema.json",
        **{**Score.model_json_schema(mode="serialization"), "description": DESCRIPTION},
    }


def build_api() -> dict[str, dict]:
    """{file stem: schema} for each booth API message."""
    out = {}
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema(mode="validation")
        about = (model.__doc__ or "").strip()
        out[name] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://github.com/becker929/zpkt/lib/contracts/{name}.schema.json",
            **schema,
            "description": f"{about} {API_DESCRIPTION.format(model=model.__name__)}".strip(),
        }
    return out


if __name__ == "__main__":
    (CONTRACTS / "score.schema.json").write_text(json.dumps(build(), indent=2) + "\n")
    for name, schema in build_api().items():
        (CONTRACTS / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote score.schema.json and {len(SCHEMAS)} booth-*.schema.json", file=sys.stderr)
