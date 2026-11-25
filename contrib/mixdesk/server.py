"""The HW002 mix desk's server, now zpkt.app.web. This name stays so the same command line works:

    uv run python contrib/mixdesk/server.py      # http://127.0.0.1:8985, needs HW002_121_pp_finish in Live

It starts the app (zpkt.app): the old desk page at / and the new shell at /app/. Imported, it is that module itself
(so the old tests and scripts that import `server` see the same names).
"""

import sys

from zpkt.app import web as _moved
from zpkt.app.web import *  # noqa: F403  (for type checkers; at run time the module is replaced below)

if __name__ == "__main__":
    _moved.main()
else:
    sys.modules[__name__] = _moved
