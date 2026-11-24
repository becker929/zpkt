"""The old name of ears.meters, kept so `import mlab`, `python -m mlab` and `uv run mlab` keep working.

mlab was its own project until 24 Nov 2026; its calibrated meters are now ears.meters. Every `mlab.<module>` is
the same module object as `ears.meters.<module>` (not a copy), loaded only when first imported, so monkeypatching
either name changes both. hands runs `from mlab import io, loudness` in a subprocess
(hands/src/hands/library/inventory.py), and the lab's spikes import mlab.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from types import ModuleType

from ears.meters import *  # noqa: F403  (the package's own names: __version__)
from ears.meters import __version__ as __version__

TARGET = "ears.meters"


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Finds mlab.<name> and hands back ears.meters.<name>, the module itself."""

    def __init__(self) -> None:
        self._specs: dict[str, importlib.machinery.ModuleSpec | None] = {}

    def find_spec(
        self, fullname: str, path: object = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith(__name__ + ".") or fullname == __name__ + ".__main__":
            return None  # mlab.__main__ is this package's own (`python -m mlab`)
        return importlib.machinery.ModuleSpec(fullname, self)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        module = importlib.import_module(TARGET + spec.name[len(__name__) :])
        self._specs[spec.name] = module.__spec__  # the import system overwrites it next; exec_module puts it back
        return module

    def exec_module(self, module: ModuleType) -> None:
        """Nothing to run (the module was loaded under its real name); give it back its own spec."""
        module.__spec__ = self._specs.pop(module.__spec__.name if module.__spec__ else "", module.__spec__)


if not any(isinstance(finder, _Alias) for finder in sys.meta_path):
    sys.meta_path.insert(0, _Alias())
