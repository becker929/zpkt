"""Projects: the board, the files behind it, and the rules they obey.

``model`` is pure — the shape of a document, what a commit freezes, and every
rule the generated JSON Schema cannot carry. ``store`` is the effectful shell —
the directory of files, the locks that keep two writers apart, and the SQLite
cache in front of it.

The files in ``audio-browser/projects/`` are the truth. The index is a cache.
"""

from .model import COLUMNS, PLACEMENTS, Column, Issue, Placement
from .store import Caps, Loaded, ProjectError, ProjectStore

__all__ = [
    "COLUMNS",
    "PLACEMENTS",
    "Caps",
    "Column",
    "Issue",
    "Loaded",
    "Placement",
    "ProjectError",
    "ProjectStore",
]
