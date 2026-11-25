"""The mix desk's `protocol` module now lives in zpkt.app.protocol. This name stays so the old imports and tests keep working:
importing it returns that module itself (so patching it patches the real one)."""

import sys

from zpkt.app import protocol as _moved
from zpkt.app.protocol import *  # noqa: F403  (for type checkers; at run time the module is replaced below)

sys.modules[__name__] = _moved
