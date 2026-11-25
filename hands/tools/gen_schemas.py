"""Write hands' contracts in lib/contracts from the Pydantic models.

The committed schemas were hand-written and had drifted (ProjectConfig was
missing sample_base, mid_layer and arrangement). The models are the source
of truth; tests/test_contract.py fails if a committed file is stale.

    uv run python tools/gen_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from zpkt.live.desk import Desk
from zpkt.live.library.models import Inventory
from zpkt.live.models import Feedback, ProjectConfig
from zpkt.live.page import Page

CONTRACTS = Path(__file__).resolve().parents[2] / "lib" / "contracts"
DESCRIPTIONS = {
    "project-config": "A declarative Live project for hands to build. Generated from src/zpkt/live/models.py — do not edit by hand.",
    "feedback": "A listener's comment on a render, captured by hands' vibe server. Generated from src/zpkt/live/models.py — do not edit by hand.",
    "desk": "The mix desk recipe's desk (contrib/mixdesk/recipe.py writes it; `hands live state diff|put` read it as a partial state). Generated from src/zpkt/live/desk.py — do not edit by hand.",
    "page": "A page of controls for the one interface (<sets_dir>/pages/<set>/<id>.json): what an agent writes for 'I want to change this'. Version 2 of the mix desk's made surface. Generated from src/zpkt/live/page.py — do not edit by hand.",
    "inventory": "Each WIP track's place in the seven workflow steps (contrib/docs/workflow.md), from `hands library inventory --json`. Generated from src/zpkt/live/library/models.py — do not edit by hand.",
}


def build(name: str, model) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/becker929/zpkt/lib/contracts/{name}.schema.json",
        **{**model.model_json_schema(mode="serialization"), "description": DESCRIPTIONS[name]},
    }


MODELS = {"project-config": ProjectConfig, "feedback": Feedback, "inventory": Inventory, "desk": Desk, "page": Page}

if __name__ == "__main__":
    for name, model in MODELS.items():
        (CONTRACTS / f"{name}.schema.json").write_text(json.dumps(build(name, model), indent=2) + "\n")
        print(f"wrote {name}.schema.json", file=sys.stderr)
