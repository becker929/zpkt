#!/usr/bin/env python3
"""Check that Python and Zod accept exactly the same project documents.

Zod is the source of truth and ``npm run schema`` emits JSON Schema from it.
That emission is the only thing keeping the two languages together, so it is
checked here rather than assumed: every case below is put to ``jsonschema`` in
Python and to ``projectDocumentSchema`` in Zod, and any document the two judge
differently is a failure. A schema that has drifted from the model is the exact
failure the one-definition rule exists to prevent, and it is silent until
something reads a file the other language wrote.

Run it from ``frontend/``::

    ../.venv/bin/python scripts/check-schema.py

Exits 0 when the two languages agree on every case, and 1 otherwise, printing
each disagreement.

Two rules cannot be written in draft 7 and are deliberately not tested here:
membership is a set, and the instants do not go backwards. Those live in
``checkProject`` in TypeScript and must be mirrored in Python after validation.
The schema is necessary, not sufficient.
"""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

FRONTEND = Path(__file__).resolve().parent.parent
SCHEMA = FRONTEND.parent / "schemas" / "project.schema.json"

HASH_A = "a" * 64
HASH_B = "b" * 64
DIGEST = "c" * 64


def sound(h: str) -> dict[str, Any]:
    return {"hash": h, "added_at": "2026-09-16T21:10:00Z", "role": None, "note": ""}


def stored() -> dict[str, Any]:
    """A project in the first column: no commits, still gathering sounds."""
    return {
        "schema_version": 1,
        "id": "2026-09-16-rust-and-rebar",
        "name": "rust and rebar",
        "column": "stored",
        "created_at": "2026-09-16T21:04:00Z",
        "updated_at": "2026-09-16T21:40:00Z",
        "notes": "",
        "abandoned": None,
        "commits": [],
        "sounds": [sound(HASH_A), sound(HASH_B)],
    }


def collage() -> dict[str, Any]:
    """One column further on, so the chain carries exactly one entry."""
    doc = stored()
    doc["column"] = "collage"
    doc["commits"] = [{"column": "stored", "at": "2026-09-16T22:00:00Z", "digest": DIGEST}]
    return doc


def enrich() -> dict[str, Any]:
    doc = collage()
    doc["column"] = "enrich"
    doc["commits"] = [
        {"column": "stored", "at": "2026-09-16T22:00:00Z", "digest": DIGEST},
        {"column": "collage", "at": "2026-09-17T09:00:00Z", "digest": DIGEST},
    ]
    return doc


def released() -> dict[str, Any]:
    doc = enrich()
    doc["column"] = "released"
    doc["commits"] = doc["commits"] + [
        {"column": "enrich", "at": "2026-09-17T10:00:00Z", "digest": DIGEST}
    ]
    return doc


def abandoned_out_of(column: str) -> dict[str, Any]:
    doc = {"stored": stored, "collage": collage, "enrich": enrich}[column]()
    doc["abandoned"] = {"at": "2026-09-17T11:00:00Z", "from": column, "reason": "the kick never sat right."}
    return doc


def edited(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A copy of ``document`` with one key set, for the one-field-wrong cases."""
    out = deepcopy(document)
    out[path] = value
    return out


def dropped(document: dict[str, Any], key: str) -> dict[str, Any]:
    out = deepcopy(document)
    out.pop(key)
    return out


# Every case: a name, the document, and what both languages must say about it.
CASES: list[tuple[str, Any, bool]] = [
    ("a project in stored", stored(), True),
    ("a project in collage, one commit", collage(), True),
    ("a project in enrich, two commits", enrich(), True),
    ("a released project, three commits", released(), True),
    ("abandoned out of stored", abandoned_out_of("stored"), True),
    ("abandoned out of collage, chain kept", abandoned_out_of("collage"), True),
    ("abandoned out of enrich, chain kept", abandoned_out_of("enrich"), True),
    ("an empty reason", edited(abandoned_out_of("collage"), "abandoned",
                               {"at": "2026-09-17T11:00:00Z", "from": "collage", "reason": ""}), True),
    ("no sounds at all", edited(stored(), "sounds", []), True),

    # The chain is the invariant the four branches carry. None of these can be
    # written as an order of events, so neither language may accept one.
    ("collage with no stored commit", edited(collage(), "commits", []), False),
    ("stored carrying a commit", edited(stored(), "commits",
                                        [{"column": "stored", "at": "2026-09-16T22:00:00Z", "digest": DIGEST}]), False),
    ("collage naming the wrong stage", edited(collage(), "commits",
                                              [{"column": "collage", "at": "2026-09-16T22:00:00Z", "digest": DIGEST}]), False),
    ("enrich with the chain out of order", edited(enrich(), "commits", [
        {"column": "collage", "at": "2026-09-16T22:00:00Z", "digest": DIGEST},
        {"column": "stored", "at": "2026-09-17T09:00:00Z", "digest": DIGEST},
    ]), False),
    ("released with two commits", edited(released(), "commits", released()["commits"][:2]), False),
    ("a released project claiming it was abandoned", edited(
        released(), "abandoned",
        {"at": "2026-09-17T11:00:00Z", "from": "enrich", "reason": ""}), False),

    # `abandoned` is a field, never a column. A fifth branch would have to allow
    # a chain of any length against it, which is the invariant above given away.
    ("abandoned written as a column", edited(stored(), "column", "abandoned"), False),
    ("abandoned as a bare true", edited(stored(), "abandoned", True), False),
    ("abandoned out of released", edited(abandoned_out_of("collage"), "abandoned",
                                         {"at": "2026-09-17T11:00:00Z", "from": "released", "reason": ""}), False),
    ("an abandonment with no instant", edited(stored(), "abandoned", {"from": "stored", "reason": ""}), False),
    ("an extra key in the abandonment", edited(stored(), "abandoned", {
        "at": "2026-09-17T11:00:00Z", "from": "stored", "reason": "", "by": "me"}), False),
    ("abandoned missing entirely", dropped(stored(), "abandoned"), False),

    # The field that was taken out of the model. A file still carrying it is a
    # file written against an older schema, and both languages have to say so
    # rather than one of them keeping it alive.
    ("a leftover bpm key", edited(stored(), "bpm", 145), False),
    ("any other extra key", edited(stored(), "colour", "rust"), False),

    # The trailing newline. Python applies a pattern with `re.search`, where `$`
    # also matches before a final newline, so `^[0-9a-f]{64}$` would accept this
    # in Python and Zod would not. The patterns end in a negative lookahead for
    # that reason, and this is the case that says the fix survived regeneration.
    ("a hash with a trailing newline", edited(stored(), "sounds", [sound(HASH_A + "\n")]), False),
    ("a digest with a trailing newline", edited(collage(), "commits", [
        {"column": "stored", "at": "2026-09-16T22:00:00Z", "digest": DIGEST + "\n"}]), False),
    ("an id with a trailing newline", edited(stored(), "id", "2026-09-16-rust-and-rebar\n"), False),
    ("a name with a trailing newline", edited(stored(), "name", "rust and rebar\n"), False),
    ("an instant with a trailing newline", edited(stored(), "created_at", "2026-09-16T21:04:00Z\n"), False),

    # Instants are compared as strings, so they have to be UTC and have to be
    # times. `format: date-time` is advisory in Python; the pattern is what
    # actually holds this line.
    ("a local time", edited(stored(), "created_at", "2026-09-16T21:04:00+02:00"), False),
    ("a time with no zone", edited(stored(), "created_at", "2026-09-16T21:04:00"), False),
    ("the ninety-ninth month", edited(stored(), "created_at", "2026-99-99T99:99:99Z"), False),
    ("fractional seconds", edited(stored(), "created_at", "2026-09-16T21:04:00.250Z"), True),

    ("an upper case id", edited(stored(), "id", "2026-09-16-Rust"), False),
    ("an id with a double hyphen", edited(stored(), "id", "2026-09-16--rust"), False),
    ("a name with a leading space", edited(stored(), "name", " rust"), False),
    ("an empty name", edited(stored(), "name", ""), False),
    ("a hash in upper case", edited(stored(), "sounds", [sound("A" * 64)]), False),
    ("a hash of the wrong length", edited(stored(), "sounds", [sound("a" * 63)]), False),
    ("a role that is empty rather than null", edited(stored(), "sounds", [
        {"hash": HASH_A, "added_at": "2026-09-16T21:10:00Z", "role": "", "note": ""}]), False),
    ("a role that is set", edited(stored(), "sounds", [
        {"hash": HASH_A, "added_at": "2026-09-16T21:10:00Z", "role": "kick", "note": ""}]), True),
    ("a schema version from the future", edited(stored(), "schema_version", 2), False),
    ("a column nobody has heard of", edited(stored(), "column", "mixdown"), False),
]


def python_verdicts(schema: dict[str, Any]) -> list[bool]:
    from jsonschema import Draft7Validator

    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    return [validator.is_valid(document) for _, document, _ in CASES]


def zod_verdicts() -> list[dict[str, Any]]:
    documents = json.dumps([document for _, document, _ in CASES])
    result = subprocess.run(
        ["node", "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON", "scripts/zod-verdicts.mjs"],
        input=documents,
        capture_output=True,
        text=True,
        cwd=FRONTEND,
        check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    if not SCHEMA.exists():
        print(f"no generated schema at {SCHEMA}. run `npm run schema` first.", file=sys.stderr)
        return 1

    schema = json.loads(SCHEMA.read_text())
    python = python_verdicts(schema)
    zod = zod_verdicts()

    failures = 0
    for (name, _document, expected), py_ok, zod_result in zip(CASES, python, zod):
        zod_ok = bool(zod_result["ok"])
        if py_ok == zod_ok == expected:
            continue
        failures += 1
        print(f"FAIL {name}")
        print(f"     expected {'accepted' if expected else 'refused'}")
        print(f"     python   {'accepted' if py_ok else 'refused'}")
        print(f"     zod      {'accepted' if zod_ok else 'refused'}")
        if zod_result["issues"]:
            print(f"     zod said {'; '.join(zod_result['issues'])}")

    print(f"{len(CASES) - failures} of {len(CASES)} cases agree between Python and Zod")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
