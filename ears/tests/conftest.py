"""Shared fixtures for the meters' tests: a throwaway lab folder for the CLI, and output with the temporary path
masked."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mlab" / "calibration"))  # checks.py: the known-answer signals


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The CLI's lab root (reports/, audio/renders/) moved to a temporary folder."""
    from mlab import cli

    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.setattr(cli, "LAB", str(root))
    return root


@pytest.fixture
def masked(tmp_path: Path):
    """A function that replaces the temporary folder in printed output with <tmp>."""

    def mask(s: str) -> str:
        return s.replace(str(tmp_path) + os.sep, "<tmp>/").replace(str(tmp_path), "<tmp>")

    return mask
