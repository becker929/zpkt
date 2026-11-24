"""The old name of zpkt.audio.meters, kept so `import mlab`, `python -m mlab` and `uv run mlab` keep working.

mlab was its own project until 24 Nov 2026; its calibrated meters are now zpkt.audio.meters. Every `mlab.<module>`
is the same module object as `zpkt.audio.meters.<module>` (not a copy), loaded only when first imported, so
monkeypatching either name changes both (zpkt._aliases). The lab's spikes import mlab.
"""

from __future__ import annotations

from zpkt._aliases import install
from zpkt.audio.meters import *  # noqa: F403  (the package's own names: __version__)
from zpkt.audio.meters import __version__ as __version__

install({"mlab": "zpkt.audio.meters"}, own=("mlab",))
