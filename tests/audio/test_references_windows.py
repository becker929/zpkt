"""The two boundaries a reference crosses (refs.json and a folder of files) and the window arithmetic."""

from __future__ import annotations

import json

import pytest
from zpkt.audio.meters import references, target, windows


def test_parse_refs_keeps_unknown_keys_and_filters_by_set() -> None:
    data = {
        "refs": [
            {"id": "a", "file": "a.wav", "drop": "24", "barSeconds": 1.5, "set": "hw002", "note": "kept"},
            {"id": "b", "file": "b.wav", "set": "other"},  # incomplete, but filtered out before it is read
        ]
    }
    refs = references.parse_refs(data, "refs.json", "hw002", "/base")
    assert refs == [
        {
            "id": "a",
            "file": "a.wav",
            "drop": 24.0,
            "barSeconds": 1.5,
            "set": "hw002",
            "note": "kept",
            "path": "/base/a.wav",
            "bar_s": 1.5,
        }
    ]
    assert references.parse_refs({}, "refs.json") == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], r'refs.json: expected \{"refs": \[...\]\}, got list'),
        ({"refs": ["a.wav"]}, "refs.json: reference 0 is a str, not an object"),
        ({"refs": [{"id": "x", "file": "x.wav"}]}, "refs.json: reference x has no drop, barSeconds"),
        ({"refs": [{"file": "x.wav", "drop": "late", "barSeconds": 1}]}, "reference 0: drop and barSeconds must be"),
    ],
)
def test_parse_refs_says_which_entry_is_wrong(data, message) -> None:
    with pytest.raises(ValueError, match=message):
        references.parse_refs(data, "refs.json")


def test_load_refs_is_the_same_function_in_target(tmp_path) -> None:
    path = tmp_path / "refs.json"
    path.write_text(json.dumps({"refs": [{"id": "a", "file": "sub/a.flac", "drop": 8, "barSeconds": 0.5}]}))
    assert target.load_refs is references.load_refs
    assert references.load_refs(str(path))[0]["path"] == str(tmp_path / "sub" / "a.flac")


def test_reference_files_and_names(tmp_path) -> None:
    for name in ("b.WAV", "a.flac", "c.txt", "d.m4a", ".e.ogg"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "f.wav").mkdir()
    files = references.reference_files(str(tmp_path))
    assert [p.rsplit("/", 1)[1] for p in files] == ["a.flac", "b.WAV", "d.m4a", "f.wav"]
    assert references.reference_files(str(tmp_path / "missing")) == []
    assert references.reference_name("/x/KSMS - Roses Of Flesh And Blood.wav", 18) == "KSMS - Roses Of Fl"


def test_windows_and_segments() -> None:
    assert windows.windows(24.0, 1.5) == {"build": (0.0, 24.0), "drop": (24.0, 48.0)}
    assert windows.windows(10.0, 0.5, {"drop": None, "tail": (16, 20)}) == {"build": (2.0, 10.0), "tail": (18.0, 20.0)}
    x = list(range(100))
    keep, skipped = windows.segments(x, 10, {"a": (-1.0, 3.0), "b": (8.0, 12.0), "c": (9.9, 12.0)}, bar_s=0.5)
    assert keep == {"a": ((0.0, 3.0), x[0:30]), "b": ((8.0, 10.0), x[80:100])}
    assert skipped == {"c": "0.10 s inside the file, needs 2.00 s (4 bars)"}
    _, skipped = windows.segments(x, 10, {"c": (9.9, 12.0)})
    assert skipped == {"c": "0.10 s inside the file, needs 0.40 s"}
    assert target.windows is windows.windows and target.DEFAULT_DROP_S == 24.0 and target.DEFAULT_BAR_S == 1.5
