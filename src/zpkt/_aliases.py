"""Old import names that still work: `hands` is zpkt.live, `ears` is zpkt.audio, `mlab` is zpkt.audio.meters.

An alias hands back the module itself, not a copy: `import hands.live.state` and `import zpkt.live.state` give the
same module object, so monkeypatching either name changes both. Each old package (src/hands, src/ears, src/mlab)
calls `install` with its table of prefixes. The longest matching prefix wins, which is how hands.live.cli becomes
zpkt.live.live_cli while every other hands.live.X becomes zpkt.live.X.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from types import ModuleType


class Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Finds old.<name> and loads new.<name> under its real name, then hands that module back."""

    def __init__(self, prefixes: dict[str, str], own: frozenset[str]) -> None:
        self.prefixes = prefixes  # old dotted prefix -> new dotted prefix
        self.own = own  # old names that are real modules of the old package (left to the normal finders)
        self._specs: dict[str, importlib.machinery.ModuleSpec | None] = {}

    def target(self, fullname: str) -> str | None:
        """The new name for an old one, or None when this alias does not cover it."""
        if fullname in self.own or fullname.endswith(".__main__"):
            return None  # `python -m old.pkg` runs the real package's __main__ through the normal finders
        for old in sorted(self.prefixes, key=len, reverse=True):
            if fullname == old or fullname.startswith(old + "."):
                return self.prefixes[old] + fullname[len(old) :]
        return None

    def find_spec(
        self, fullname: str, path: object = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        return importlib.machinery.ModuleSpec(fullname, self) if self.target(fullname) else None

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        new = self.target(spec.name)
        assert new is not None  # find_spec only answers for names it covers
        module = importlib.import_module(new)
        self._specs[spec.name] = module.__spec__  # the import system overwrites it next; exec_module puts it back
        return module

    def exec_module(self, module: ModuleType) -> None:
        """Nothing to run (the module was loaded under its real name); give it back its own spec."""
        module.__spec__ = self._specs.pop(module.__spec__.name if module.__spec__ else "", module.__spec__)


def install(prefixes: dict[str, str], own: tuple[str, ...] = ()) -> None:
    """Put an alias for `prefixes` first on sys.meta_path, once per table."""
    for finder in sys.meta_path:
        if isinstance(finder, Alias) and finder.prefixes == prefixes:
            return
    sys.meta_path.insert(0, Alias(prefixes, frozenset(own)))
