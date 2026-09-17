"""Content-addressed index for a personal audio collection.

The BLAKE3 digest of a file's bytes is the identity of a sound. Paths are
aliases that point at a digest.
"""

__version__ = "0.1.0"

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac", ".ogg", ".opus"}
)
"""Extensions counted as audio. Lowercase, leading dot. From 01-spec.md."""
