"""Settings for every test run from the repo root.

Under `pytest -n auto` (make quick) each worker gets its own numba cache. Twelve workers compiling librosa's numba
functions into one cache at once corrupted it, and the next reader crashed with SIGSEGV (25 Nov 2026). A folder per
worker keeps the cache warm between runs without two writers. Subprocesses the tests start inherit it.
"""

from __future__ import annotations

import os
from pathlib import Path

_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _worker and "NUMBA_CACHE_DIR" not in os.environ:
    os.environ["NUMBA_CACHE_DIR"] = str(Path.home() / ".cache" / "zpkt-tests" / "numba" / _worker)
