"""The files the desk writes outside git keep their bytes: the recipe's "desk" and match.py's snapshots, read from
FakeLive's HW002-like set and compared with what the code wrote before the upgrade (tests/data, made up values)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hands.live.ops import LiveOps
from hands.testing import FakeLive, hw002_like

DATA = Path(__file__).resolve().parent / "data"
REGENERATE = os.environ.get("MIXDESK_REGENERATE") == "1"  # only to make the files from the code before the upgrade


@pytest.fixture()
def modules():
    import match
    import recipe

    return recipe, match


def read_desk(recipe, match, live) -> dict:
    return recipe.read_desk(LiveOps(live))


def snapshot(match, live, tmp_path) -> Path:
    return match.snapshot(LiveOps(live), "golden", folder=tmp_path)


def check(name: str, text: str) -> None:
    path = DATA / name
    if REGENERATE:
        path.write_text(text)
    assert text == path.read_text()


def test_the_recipes_desk_keeps_its_bytes(modules):
    recipe, match = modules
    with FakeLive(hw002_like()) as live:
        desk = read_desk(recipe, match, live)
    desk["made"] = 0.0
    check("recipe-desk.json", json.dumps(desk))


def test_a_match_snapshot_keeps_its_bytes(modules, tmp_path):
    _recipe, match = modules
    with FakeLive(hw002_like()) as live:
        path = snapshot(match, live, tmp_path)
    snap = json.loads(path.read_text())
    snap["at"] = "2026-11-24 00:00:00"
    check("match-snapshot.json", json.dumps(snap, indent=1))


def test_importing_the_live_scripts_changes_no_environment():
    import subprocess
    import sys

    code = ("import os, sys; sys.path.insert(0, sys.argv[1]); before = dict(os.environ); "
            "import match, recipe, workspace; print(before == dict(os.environ))")
    out = subprocess.run([sys.executable, "-c", code, str(DATA.parents[1])], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "True"


def test_apply_puts_a_written_desk_back_into_a_moved_set(modules, monkeypatch):
    recipe, _match = modules
    # the set already has the desk's devices; FakeLive's Echo lacks the "Dry Wet" workspace.devices sets
    monkeypatch.setattr(recipe.W, "devices", lambda live: None)
    desk = json.loads((DATA / "recipe-desk.json").read_text())
    desk.pop("monitor")  # the monitor tracks' files are made up; monitor.ensure needs real ones
    with FakeLive(hw002_like()) as live:
        live.run("find_track('Kick bus').mixer_device.volume.value = 0.3\n"
                 "find_track('Hats bus').devices[0].parameters[1].value = 0.0\n"
                 "find_track('kick').devices[0].parameters[0].value = 0.0\nresult = 'ok'")
        ops = LiveOps(live)
        assert recipe.apply_desk(ops, desk, log=lambda *a: None) == []
        again = recipe.read_desk(ops)
    again["made"], again["monitor"] = 0.0, []
    assert {k: v for k, v in again.items() if k != "monitor"} == {**desk, "made": 0.0}
