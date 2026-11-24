"""The old name of zpkt.live, kept so `import hands` and every `hands.X` keep working for a while.

hands.X and hands.live.X are the modules zpkt.live.X themselves (hands.live.cli is zpkt.live.live_cli); see
zpkt._aliases. New code imports zpkt.live.
"""

from zpkt._aliases import install
from zpkt.live import __version__ as __version__

install(
    {"hands": "zpkt.live", "hands.live": "zpkt.live", "hands.live.cli": "zpkt.live.live_cli"},
    own=("hands", "hands.live"),
)
