"""zpkt.audio: measuring renders (until 24 Nov 2026 the `ears` package; `import ears` still works).

Profiles with an embedding, a reference corpus, and the calibrated meters in zpkt.audio.meters (once `mlab`).
"""

from .analyzer import analyze
from .models import AudioProfile

__all__ = ["AudioProfile", "analyze"]
