"""The mix desk's `deskstate` module now lives in zpkt.app.deskstate. This name stays so the old imports and tests keep working:
importing it returns that module itself (so patching it patches the real one)."""

import sys

from zpkt.app import deskstate as _moved
from zpkt.app.deskstate import *  # noqa: F403  (for type checkers; at run time the module is replaced below)

sys.modules[__name__] = _moved
