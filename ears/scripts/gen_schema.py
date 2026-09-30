"""Write lib/contracts/audio-profile.schema.json from ears' dataclasses.

The schema used to be hand-written and drifted from the code (source_path
vs audio_path, centroid_hz vs spectral_centroid_mean). Generating it from
the dataclasses makes the dataclasses the single source of truth;
tests/test_contract.py fails if the committed file is stale.

    uv run python scripts/gen_schema.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
import types
import typing
from pathlib import Path

from ears.models import AudioProfile

OUT = Path(__file__).resolve().parents[2] / "lib" / "contracts" / "audio-profile.schema.json"


def _schema(tp) -> dict:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        s = _schema(inner[0])
        return {"anyOf": [s, {"type": "null"}]} if type(None) in args else s
    if origin is list:
        return {"type": "array", "items": _schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object", "additionalProperties": _schema(args[1]) if len(args) > 1 else {}}
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return {
            "type": "object",
            "properties": {f.name: _schema(hints[f.name]) for f in dataclasses.fields(tp)},
            "additionalProperties": False,
        }
    return {str: {"type": "string"}, int: {"type": "integer"}, float: {"type": "number"},
            bool: {"type": "boolean"}}.get(tp, {})


def build() -> dict:
    body = _schema(AudioProfile)
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://github.com/becker929/zpkt/lib/contracts/audio-profile.schema.json",
        "title": "AudioProfile",
        "description": "What ears measured about one audio file. Produced by `ears analyze --json`; "
                       "generated from ears/src/ears/models.py — do not edit by hand.",
        "required": ["clip_id", "audio_path"],
        **body,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}", file=sys.stderr)
