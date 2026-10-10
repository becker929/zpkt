"""taste's Verdict must match lib/contracts/verdict.schema.json (generated)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

from taste.models import Verdict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "prototypes" / "taste" / "scripts"))
import gen_schema  # noqa: E402


def test_committed_schema_is_current() -> None:
    committed = json.loads((ROOT / "lib" / "contracts" / "verdict.schema.json").read_text())
    assert committed == gen_schema.build(), "stale contract: run `uv run python scripts/gen_schema.py` in prototypes/taste/"


def test_instance_validates() -> None:
    v = Verdict(clip_id="c", score=4, rationale="r", suggestions=["s"], retrieved_ids=["a"], model="m")
    jsonschema.validate(json.loads(v.model_dump_json()), gen_schema.build())
