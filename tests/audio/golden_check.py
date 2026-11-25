"""Golden files: what the meters report today, so a refactor can prove they report the same.

`check(name, value)` compares a value with `golden/<name>.json`; `text(name, s)` compares a string with
`golden/<name>.txt`. A golden that stops matching means a reported number or line changed. That is a capability
change: stop and report it instead of rewriting the file. Write a golden only for a new test, with GOLDEN_WRITE=1.

The goldens were written on an Apple-silicon Mac (`HOME`). There, floats match to 1e-9 relative, and GOLDEN_EXACT=1
asks for bit-for-bit equality (how a refactor on that Mac is checked). On any other platform (CI runs Linux on x86)
the FFT, BLAS and float32 maths round differently, by up to 1.2e-5 relative in what these tests report, so floats
match to 1e-4 there. A test whose numbers come out of an optimizer is marked `home_only`: its path, and so its
iteration counts, depend on the last bits.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

GOLDEN = Path(__file__).parent / "golden"
WRITE = bool(os.environ.get("GOLDEN_WRITE"))
EXACT = bool(os.environ.get("GOLDEN_EXACT"))
HOME = sys.platform == "darwin" and platform.machine() == "arm64"
REL, ABS = (0.0, 0.0) if EXACT else (1e-9, 1e-12) if HOME else (1e-4, 1e-9)

home_only = pytest.mark.skipif(not HOME, reason="an optimizer's path depends on the platform's last bits")


def plain(v: Any) -> Any:
    """numpy scalars and arrays, tuples and dataclasses as plain JSON values (key order kept)."""
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return plain(dataclasses.asdict(v))
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return plain(v.tolist())
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v)
    return v


def _same_float(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= max(ABS, REL * max(abs(a), abs(b)))


def diff(got: Any, want: Any, path: str = "$") -> list[str]:
    """Every place where got differs from want: keys and their order, list lengths, types, values."""
    if isinstance(want, dict):
        if not isinstance(got, dict) or list(got) != list(want):
            return [f"{path}: keys {list(got) if isinstance(got, dict) else type(got).__name__} != {list(want)}"]
        return [d for k in want for d in diff(got[k], want[k], f"{path}.{k}")]
    if isinstance(want, list):
        if not isinstance(got, list) or len(got) != len(want):
            return [f"{path}: {got!r:.200} != {want!r:.200}"]
        return [d for i, (g, w) in enumerate(zip(got, want, strict=True)) for d in diff(g, w, f"{path}[{i}]")]
    if type(got) is not type(want):
        return [f"{path}: type {type(got).__name__} ({got!r}) != {type(want).__name__} ({want!r})"]
    if isinstance(want, float):
        return [] if _same_float(got, want) else [f"{path}: {got!r} != {want!r}"]
    return [] if got == want else [f"{path}: {got!r} != {want!r}"]


def check(name: str, value: Any) -> None:
    got = plain(value)
    path = GOLDEN / f"{name}.json"
    if WRITE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1) + "\n")
        return
    if not path.exists():
        raise AssertionError(f"no golden {path.name}: write it once with GOLDEN_WRITE=1")
    problems = diff(got, json.loads(path.read_text()))
    assert not problems, f"{name}: {len(problems)} differences, first:\n" + "\n".join(problems[:15])


def text(name: str, s: str) -> None:
    path = GOLDEN / f"{name}.txt"
    if WRITE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(s)
        return
    if not path.exists():
        raise AssertionError(f"no golden {path.name}: write it once with GOLDEN_WRITE=1")
    want = path.read_text()
    if s != want:
        got_lines, want_lines = s.splitlines(), want.splitlines()
        first = next(
            (i for i, (g, w) in enumerate(zip(got_lines, want_lines, strict=False)) if g != w),
            min(len(got_lines), len(want_lines)),
        )
        raise AssertionError(
            f"{name}: output differs from line {first + 1}:\n"
            f"  got:  {got_lines[first] if first < len(got_lines) else '<end>'}\n"
            f"  want: {want_lines[first] if first < len(want_lines) else '<end>'}"
        )
