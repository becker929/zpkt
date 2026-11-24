"""The desk's core (the reducer, the messages, the history, the pager's logic) knows no set and no desk file: it
takes a page and a set name, so a second interface can import it unchanged."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
CORE = ("deskstate.py", "protocol.py", "history.py", "pagercore.py")


@pytest.mark.parametrize("name", CORE)
def test_a_core_module_names_no_set_and_reads_no_desk_file(name):
    source = (HERE / name).read_text()
    assert "desk.json" not in source and "HW002" not in source and "sources.json" not in source
    assert "__file__" not in source  # nothing found beside itself: what it reads is passed in
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
    }
    assert not imported & {"server", "surfaces", "recipe", "finishing", "workspace", "monitor"}


def test_the_history_takes_its_set_name_and_folders(tmp_path):
    import history

    h = history.History("ANY SET", {}, directory=tmp_path / "h", checkpoints=tmp_path / "cp", clock=lambda: 1.0)
    h.baseline({"0:f1": {"key": "Bus/volume", "s": "0 dB", "r": 0.5}})
    assert h.seen("Bus/volume", "-1 dB", 0.4)
    assert (tmp_path / "h" / "ANY SET.json").exists() and h.folder() == tmp_path / "cp"
