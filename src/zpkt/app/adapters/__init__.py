"""Adapters: how the world reaches the app. Each turns what it hears into Commands for the bus.

An adapter is a small object with a name, `start()` and `stop()`. It gets an AppContext: the bus to submit Commands to,
the desk (the app's services, read only for what to show) and the settings. It never opens a connection to Live and
never imports zpkt.live to change anything: Live is reached only through the bus.

To add one, put a module in this package that defines `ADAPTER = AdapterSpec("name", make)`, where `make(context)`
returns the adapter. `discover()` finds every such module, so the core is not edited. The Web adapter (web.py) is the
first; the MiniLab (MIDI), the API and the agents come after it.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from zpkt.app.bus import Bus
    from zpkt.app.desk import Desk, Settings


@dataclass(frozen=True)
class AppContext:
    """What an adapter is given."""

    bus: Bus
    desk: Desk
    settings: Settings


class Adapter(Protocol):
    """One way in to the app."""

    name: str

    def start(self) -> None:
        """Begin listening. Returns at once; any serving happens in the adapter's own threads."""
        ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class AdapterSpec:
    """How to make an adapter: its name and a factory."""

    name: str
    make: Callable[[AppContext], Adapter]


def discover() -> dict[str, AdapterSpec]:
    """Every adapter module in this package that defines ADAPTER, by name."""
    found: dict[str, AdapterSpec] = {}
    for info in pkgutil.iter_modules(__path__):
        spec = getattr(importlib.import_module(f"{__name__}.{info.name}"), "ADAPTER", None)
        if isinstance(spec, AdapterSpec):
            found[spec.name] = spec
    return found


def create(names: list[str], context: AppContext) -> list[Adapter]:
    """The named adapters, made. An unknown name is an error that lists the known ones."""
    known = discover()
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f"no adapter {', '.join(unknown)}; the adapters are {', '.join(sorted(known))}")
    return [known[n].make(context) for n in names]
