"""pagercore.py, shared with the pager: the MiniLab's decisions (pickup, pages, the full map) as plain functions.

pager.py runs inside Live and loads contrib/mixdesk/pagercore.py by path, since Live's Python cannot import zpkt. The
app loads the same file the same way, so there is one copy of the rules and the two cannot drift.
"""

from __future__ import annotations

import importlib.util
import threading
from types import ModuleType

from zpkt.app.desk import mixdesk_dir

_lock = threading.Lock()
_loaded: dict[str, ModuleType] = {}


def pagercore() -> ModuleType:
    """The shared module (loaded once per folder: ZPKT_MIXDESK_DIR names another)."""
    path = mixdesk_dir() / "pagercore.py"
    with _lock:
        module = _loaded.get(str(path))
        if module is None:
            spec = importlib.util.spec_from_file_location("zpkt_app_pagercore", path)
            if spec is None or spec.loader is None:
                raise FileNotFoundError(f"the pager's shared rules are not at {path}; set ZPKT_MIXDESK_DIR")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _loaded[str(path)] = module
        return module
