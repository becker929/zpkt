"""zpkt.app: reserved for the one interface, the page Anthony works in.

It will grow out of the mix desk's server (contrib/mixdesk/server.py), which moves here as its first tenant when
the interface build starts, not before. Until then `zpkt app` says so and does nothing.
"""

from __future__ import annotations

import sys

NOT_BUILT = (
    "zpkt app is not built yet: the one interface will grow out of the mix desk's server. "
    "Until then run the mix desk: uv run python contrib/mixdesk/server.py"
)


def main() -> None:
    """`zpkt app`: say it is not built yet, and exit 1 (it did nothing)."""
    sys.exit(NOT_BUILT)
