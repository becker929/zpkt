"""The song.* commands' answers match lib/contracts/song.schema.json, and the schema names every command."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tests.app.test_song import MIX_SET, open_set, quick_live, song_rig  # noqa: F401  (fixtures)
from zpkt.app import song

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "lib" / "contracts" / "song.schema.json").read_text())


def check(name: str, instance: object) -> None:
    jsonschema.validate(instance, {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


def test_the_schema_is_a_schema_and_names_every_song_command(song_rig):  # noqa: F811
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    commands = [k for k in song_rig.rig.desk.bus.kinds() if k.startswith("song.")]
    assert sorted(commands) == sorted(SCHEMA["$defs"]["Args"]["properties"])
    assert set(song.WRITES) <= set(commands)


def test_reads_and_the_build_answer_in_the_contracts_shapes(song_rig, quick_live):  # noqa: F811
    rig = song_rig.rig
    check("List", rig.command("song.list")[1])
    check("Song", rig.command("song.show", {"id": "short-8d2a2"})[1])
    check("Recipe", rig.command("song.recipe", {"id": "short-8d2a2"})[1])
    check("Recipe", rig.command("song.recipe", {"id": "other"})[1])  # a file with only some keys
    open_set(rig, MIX_SET)
    check("Built", rig.command("song.build", {})[1])


def test_the_example_arguments_in_the_tests_match_the_schema(song_rig):  # noqa: F811
    rig = song_rig.rig
    body = {"name": "x", "bars": 8, "regions": [{"lane": "kick", "clip": "k", "start": 0, "len": 4}]}
    for kind, args in [
        ("song.save", {"id": "c-1", "body": body}),
        ("song.keep", {"id": "c-1", "key": "mix", "body": {"channels": {}}}),
        ("song.transitions", {"body": {"picks": {}}}),
        ("song.delete", {"id": "c-1"}),
    ]:
        jsonschema.validate(args, SCHEMA["$defs"]["Args"]["properties"][kind])
        assert rig.command(kind, args)[0] == 200, kind
