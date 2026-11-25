"""The old name of zpkt.audio, kept so `import ears` and every `ears.X` keep working for a while.

ears.X is the module zpkt.audio.X itself (zpkt._aliases). New code imports zpkt.audio.
"""

from zpkt._aliases import install
from zpkt.audio import AudioProfile, analyze

__all__ = ["AudioProfile", "analyze"]

install({"ears": "zpkt.audio"}, own=("ears",))
