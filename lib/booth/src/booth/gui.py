"""Live's GUI steps without keystrokes: browser loads, parameters in display units, the mixer, Save As and the
export. They are SH001's (hands/scripts/rummage/liveops.py), loaded from there rather than copied, pointed at the
booth's client and folders.

liveops stops with sys.exit("STOP: ..."); here that becomes Stop, so the runner can hold the job instead of exiting.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

from . import HOME

_PATH = Path(__file__).resolve().parents[4] / "hands" / "scripts" / "rummage" / "liveops.py"


class Stop(RuntimeError):
    """Something in Live was not as expected. The job is held and the booth closes (runner.py)."""


def _load():
    spec = importlib.util.spec_from_file_location("booth_liveops", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # its os.environ.setdefault calls change nothing: booth/__init__ set them first
    mod.EXPORT_DIR = HOME          # a parent of sets/, so the Save panel reaches it from the set's own folder
    return mod


_ops = None


def ops(client=None):
    """liveops, using `client` for its LOM calls."""
    global _ops
    if _ops is None:
        _ops = _load()
    if client is not None:
        _ops.LIVE = client
    return _ops


@contextmanager
def stops(where: str):
    """Turn liveops' and hands' stops into Stop, naming the step."""
    from hands.live.session import Guard
    from hands.live.transport import LiveError
    try:
        yield
    except SystemExit as exc:
        raise Stop(f"{where}: {exc}") from None
    except (Guard, LiveError) as exc:
        raise Stop(f"{where}: {exc}") from None
