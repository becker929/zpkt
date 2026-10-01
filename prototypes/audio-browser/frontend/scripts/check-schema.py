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


def region() -> dict[str, Any]:
    """One stamped region, exactly as the first tracer bullet writes it."""
    return {
        "id": "r1",
        "hash": HASH_A,
        "track": 0,
        "start_s": 0.0,
        "end_s": 6.4,
        "at_s": 0.0,
        "rate": 1.0,
        "gain": 1.0,
        "fade_in_s": 0.0,
        "fade_out_s": 0.0,
    }


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

    # The collage. Absent and null are the same claim, that nothing has been
    # stamped, so a file written before the field existed still validates. A
    # region carries every field from the first stamp, at its untouched value,
    # and nothing else. The cross-field rules — the hash is in the sound set,
    # the cut ends after it begins, ids are unique — live in `checkProject` and
    # its Python mirror, not here.
    ("a collage with one region", edited(collage(), "collage", {"regions": [region()]}), True),
    ("a collage with no regions", edited(collage(), "collage", {"regions": []}), True),
    ("a collage that is null", edited(collage(), "collage", None), True),
    # `collage()` above carries no `collage` key: it is a file from before the
    # field existed, and it validates as it stands.
    ("a project with no collage key at all", collage(), True),
    ("a region missing its rate", edited(collage(), "collage", {"regions": [dropped(region(), "rate")]}), False),
    ("a region with an extra key", edited(collage(), "collage", {"regions": [{**region(), "note": ""}]}), False),
    ("a region on a negative track", edited(collage(), "collage", {"regions": [{**region(), "track": -1}]}), False),
    ("a region with a fractional track", edited(collage(), "collage", {"regions": [{**region(), "track": 0.5}]}), False),
    ("a region with a rate of zero", edited(collage(), "collage", {"regions": [{**region(), "rate": 0}]}), False),
    ("a region naming a hash in upper case", edited(collage(), "collage", {"regions": [{**region(), "hash": "A" * 64}]}), False),
    ("a collage with a key beside regions", edited(collage(), "collage", {"regions": [], "bpm": 145}), False),
    ("a collage that is a bare list", edited(collage(), "collage", [region()]), False),

    # Repeats. ``loops`` arrived after regions did, so a region written
    # without it is still a region and reads as sounding once: absent and 1
    # are the same claim, exactly as absent and null are for the whole
    # ``collage`` field. ``region()`` above carries no ``loops`` key, so the
    # first collage case already pins the absent side.
    ("a region that repeats", edited(collage(), "collage", {"regions": [{**region(), "loops": 4}]}), True),
    ("a region that sounds once, said so", edited(collage(), "collage", {"regions": [{**region(), "loops": 1}]}), True),
    ("a region that repeats no times", edited(collage(), "collage", {"regions": [{**region(), "loops": 0}]}), False),
    ("a region that repeats a negative number of times",
     edited(collage(), "collage", {"regions": [{**region(), "loops": -1}]}), False),
    ("a region that repeats half a time", edited(collage(), "collage", {"regions": [{**region(), "loops": 2.5}]}), False),
    ("a region whose repeat count is text", edited(collage(), "collage", {"regions": [{**region(), "loops": "4"}]}), False),
    ("a region whose repeat count is nothing", edited(collage(), "collage", {"regions": [{**region(), "loops": None}]}), False),
]

# The rules the schema cannot carry. Every one of these passes the schema in
# both languages, and that is not a bug: draft 7 cannot compare two fields or
# look a hash up in a set. What holds each line is ``checkProject`` in
# TypeScript and ``collage_issues`` in Python, written by hand on both sides.
# The Python side is covered in ``tests/test_projects.py``; this list is what
# says the TypeScript side refuses the same documents. The third column is what
# ``checkProject`` must answer.
RULE_CASES: list[tuple[str, Any, bool]] = [
    ("checkProject: a collage with one region", edited(collage(), "collage", {"regions": [region()]}), True),
    # A project in stored has no frozen set to cut from, so it holds no
    # collage. The schema lets the key through on every branch.
    ("checkProject: a collage on a project still in stored", edited(stored(), "collage", {"regions": []}), False),
    ("checkProject: a stored project carrying a stamped region",
     edited(stored(), "collage", {"regions": [region()]}), False),
    ("checkProject: a region cutting from outside the frozen set",
     edited(collage(), "collage", {"regions": [{**region(), "hash": "d" * 64}]}), False),
    ("checkProject: a cut that ends before it begins",
     edited(collage(), "collage", {"regions": [{**region(), "start_s": 2.0, "end_s": 1.0}]}), False),
    ("checkProject: a cut of no length",
     edited(collage(), "collage", {"regions": [{**region(), "start_s": 1.0, "end_s": 1.0}]}), False),
    ("checkProject: two regions with one id",
     edited(collage(), "collage", {"regions": [region(), {**region(), "track": 1}]}), False),
]


# The bytes a `collage` commit digests. This is the freeze itself: a digest is
# the only thing that makes a commit checkable years later, so the two
# languages must write the same string for the same description or the freeze
# is one-sided.
#
# The cases that matter most are the ones about a field that arrived late.
# `loops` was added after collages already existed, so a region that leaves it
# out and a region that writes 1 are the same claim, and both must come out as
# the text the code that had never heard of the field produced. Nothing else
# keeps a digest taken before the field arrived from moving.
def _region(**fields: Any) -> dict[str, Any]:
    base = region()
    base.update(fields)
    return base


CANON_CASES: list[tuple[str, dict[str, Any]]] = [
    ("no regions at all", {"regions": []}),
    ("a region as the old code wrote it, with no loops key", {"regions": [_region()]}),
    ("the same region saying it sounds once", {"regions": [_region(loops=1)]}),
    ("a region that really repeats", {"regions": [_region(loops=7)]}),
    # Present and absent in one description, which is what a project edited
    # after the field arrived actually holds.
    ("one region with loops, one without", {"regions": [
        _region(loops=3), _region(id="r2", track=1),
    ]}),
    ("the same two, the other way round", {"regions": [
        _region(id="r2", track=1), _region(loops=3),
    ]}),
    # The rest of the rule: order, key order, integers against floats, the
    # float noise a hand-placed region really carries, and negative zero.
    ("regions out of order", {"regions": [
        _region(id="r2", track=1, at_s=0.1 + 0.2), _region(id="r1"),
    ]}),
    ("a rate and a level that are not round", {"regions": [
        _region(rate=0.327431, gain=1.75, at_s=49.612, end_s=131.0, start_s=4.0),
    ]}),
    ("negative zero", {"regions": [_region(at_s=-0.0, fade_out_s=-0.0)]}),
    ("integers written as integers", {"regions": [
        {**_region(), "at_s": 12, "rate": 1, "gain": 1, "track": 2},
    ]}),
    ("an id outside ASCII, which both languages must escape and sort alike",
     {"regions": [_region(id="ré"), _region(id="rz", track=1)]}),
]


def python_verdicts(schema: dict[str, Any]) -> list[bool]:
    from jsonschema import Draft7Validator

    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    return [validator.is_valid(document) for _, document, _ in CASES]


def zod_verdicts() -> dict[str, Any]:
    payload = json.dumps(
        {
            "documents": [document for _, document, _ in CASES + RULE_CASES],
            "collages": [collage for _, collage in CANON_CASES],
        }
    )
    result = subprocess.run(
        ["node", "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON", "scripts/zod-verdicts.mjs"],
        input=payload,
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
    answers = zod_verdicts()
    verdicts = answers["verdicts"]
    zod, rules = verdicts[: len(CASES)], verdicts[len(CASES):]

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

    # The hand-written rules. Each of these must pass the schema (or it would
    # belong in CASES) and get the listed verdict from `checkProject`.
    rule_failures = 0
    for (name, _document, expected), result in zip(RULE_CASES, rules):
        schema_ok = bool(result["ok"])
        checked_ok = bool(result["checked"])
        if schema_ok and checked_ok == expected:
            continue
        rule_failures += 1
        print(f"FAIL {name}")
        if not schema_ok:
            print("     the schema refused it, so it is not a checkProject rule; move it to CASES")
            print(f"     zod said {'; '.join(result['issues'])}")
        else:
            print(f"     expected checkProject to {'accept' if expected else 'refuse'} it")
            print(f"     checkProject {'accepted' if checked_ok else 'refused'} it")
            if result["checkedIssues"]:
                print(f"     it said {'; '.join(result['checkedIssues'])}")

    print(f"{len(RULE_CASES) - rule_failures} of {len(RULE_CASES)} checkProject rules hold")

    # The freeze. Python's `collage_input` and TypeScript's `collageInput` must
    # write the same string, and the string must not depend on whether the
    # description has been through a parser that fills defaults in.
    sys.path.insert(0, str(FRONTEND.parent / "src"))
    from audio_browser.projects.model import collage_input  # noqa: PLC0415

    canon_failures = 0
    for (name, collage), answer in zip(CANON_CASES, answers["canonical"]):
        mine = collage_input(collage)
        theirs = answer["raw"]
        after_parsing = answer["parsed"]
        if mine == theirs and after_parsing == mine:
            continue
        canon_failures += 1
        print(f"FAIL canonical text: {name}")
        print(f"     python {mine}")
        print(f"     zod    {theirs}")
        if after_parsing != mine:
            print(f"     after parsing {after_parsing}")
            print("     a default written in by the parser changed the bytes")

    # And the one claim the whole freeze rests on: a description that leaves a
    # defaulted key out writes exactly what the code that had never heard of
    # that key wrote. Checked here against the other language as well, so it
    # cannot hold on one side alone.
    absent = {"regions": [region()]}
    if "loops" in collage_input(absent) or "loops" in answers["canonical"][1]["raw"]:
        canon_failures += 1
        print("FAIL canonical text: a defaulted key was written into the freeze")
        print("     every digest taken before that key existed has moved")

    print(f"{len(CANON_CASES) - canon_failures} of {len(CANON_CASES)} canonical texts agree")
    return 1 if failures or rule_failures or canon_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
