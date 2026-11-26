"""Write hands' contracts in lib/contracts from the Pydantic models.

The committed schemas were hand-written and had drifted (ProjectConfig was
missing sample_base, mid_layer and arrangement). The models are the source
of truth; tests/live/test_contract.py fails if a committed file is stale.

    uv run python hands/tools/gen_schemas.py   (or: python -m zpkt.live.schemas)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from zpkt.live.desk import Desk
from zpkt.live.library.models import Inventory
from zpkt.live.models import ProjectConfig
from zpkt.live.page import Page
from zpkt.live.page_layout import Layout

CONTRACTS = Path(__file__).resolve().parents[3] / "lib" / "contracts"
DESCRIPTIONS = {
    "project-config": "A declarative Live project for hands to build. Generated from src/zpkt/live/models.py — do not edit by hand.",
    "desk": "The mix desk recipe's desk (contrib/mixdesk/recipe.py writes it; `hands live state diff|put` read it as a partial state). Generated from src/zpkt/live/desk.py — do not edit by hand.",
    "page": "A page of controls for the one interface (<sets_dir>/pages/<set>/<id>.json): what an agent writes for 'I want to change this'. Version 2 of the mix desk's made surface. Generated from src/zpkt/live/page.py — do not edit by hand.",
    "page-layout": "A Page as the one interface draws it (the reply of the page.layout command): one panel per MiniLab page with all 20 slots, and each control's widget and label. Generated from src/zpkt/live/page_layout.py — do not edit by hand.",
    "inventory": "Each WIP track's place in the seven workflow steps (contrib/docs/workflow.md), from `hands library inventory --json`. Generated from src/zpkt/live/library/models.py — do not edit by hand.",
}


def build(name: str, model: type[BaseModel]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/becker929/zpkt/lib/contracts/{name}.schema.json",
        **{**model.model_json_schema(mode="serialization"), "description": DESCRIPTIONS[name]},
    }


MODELS: dict[str, type[BaseModel]] = {
    "project-config": ProjectConfig,
    "inventory": Inventory,
    "desk": Desk,
    "page": Page,
    "page-layout": Layout,
}


def write_all() -> None:
    for name, model in MODELS.items():
        (CONTRACTS / f"{name}.schema.json").write_text(json.dumps(build(name, model), indent=2) + "\n")
        print(f"wrote {name}.schema.json", file=sys.stderr)


if __name__ == "__main__":
    write_all()
