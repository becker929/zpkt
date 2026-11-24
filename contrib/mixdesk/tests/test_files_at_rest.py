"""The files the desk writes outside git keep their bytes: the recipe's "desk" and match.py's snapshots, read from
FakeLive's HW002-like set and compared with what the code wrote before the upgrade (tests/data, made up values)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hands import config
from hands.live.ops import LiveOps
from hands.testing import FakeLive, hw002_like

DATA = Path(__file__).resolve().parent / "data"
REGENERATE = os.environ.get("MIXDESK_REGENERATE") == "1"  # only to make the files from the code before the upgrade


@pytest.fixture()
def modules(monkeypatch):
    """recipe and match imported without leaving their rig settings in this process."""
    before = dict(os.environ)
    import match
    import recipe

    os.environ.clear()
    os.environ.update(before)
    config.rig.cache_clear()
    yield recipe, match
    config.rig.cache_clear()


def read_desk(recipe, match, live) -> dict:
    ops = LiveOps(live)
    recipe.L = match.L = ops
    return recipe.read_desk()


def snapshot(match, live, tmp_path) -> Path:
    match.L = LiveOps(live)
    match.SNAPS = tmp_path
    return match.snapshot("golden")


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
