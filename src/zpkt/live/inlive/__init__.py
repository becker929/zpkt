"""Helpers that run unchanged in hands and inside Live.

Each module here is stdlib-only Python 3.11 (Live's own Python) and imports nothing from hands or from the others,
so it works three ways: imported by hands, loaded by file path inside Live (contrib/mixdesk/pager.py), and sent to
Live as source at the top of a code string (`with_source`). One rule lives in one place that way, instead of once in
hands and again in each code string. Their tests are hands/tests/test_inlive.py.
"""

from __future__ import annotations

from pathlib import Path

MODULES = ("tracks", "shown", "keys")


def path(module: str) -> Path:
    """The file of an inlive module, for loading it by path (importlib) where hands cannot be imported."""
    if module not in MODULES:
        raise ValueError(f"no inlive module {module!r}; there are {', '.join(MODULES)}")
    return Path(__file__).with_name(f"{module}.py")


def source(module: str) -> str:
    """An inlive module's code, to define its functions in the scope of a code string sent to Live."""
    return path(module).read_text()


def with_source(code: str, *modules: str) -> str:
    """`code` with the named inlive modules defined above it."""
    return "\n".join([*(source(m) for m in modules), code])
