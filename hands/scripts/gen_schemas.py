"""Write hands' contracts in lib/contracts from the Pydantic models.

The committed schemas were hand-written and had drifted (ProjectConfig was
missing sample_base, mid_layer and arrangement). The models are the source
of truth; tests/test_contract.py fails if a committed file is stale.

    uv run python scripts/gen_schemas.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hands.models import Feedback, ProjectConfig

CONTRACTS = Path(__file__).resolve().parents[2] / "lib" / "contracts"
DESCRIPTIONS = {
    "project-config": "A declarative Live project for hands to build. Generated from hands/src/hands/models.py — do not edit by hand.",
    "feedback": "A listener's comment on a render, captured by hands' vibe server. Generated from hands/src/hands/models.py — do not edit by hand.",
}


def build(name: str, model) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/becker929/zpkt/lib/contracts/{name}.schema.json",
        **{**model.model_json_schema(mode="serialization"), "description": DESCRIPTIONS[name]},
    }


MODELS = {"project-config": ProjectConfig, "feedback": Feedback}

if __name__ == "__main__":
    for name, model in MODELS.items():
        (CONTRACTS / f"{name}.schema.json").write_text(json.dumps(build(name, model), indent=2) + "\n")
        print(f"wrote {name}.schema.json", file=sys.stderr)
